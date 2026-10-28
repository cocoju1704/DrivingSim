package com.drivingsim.torapp

import android.content.ContentUris
import android.content.Context
import android.provider.MediaStore
import android.util.Log
import java.io.IOException
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

private const val TAG = "VideoServer"
const val VIDEO_PORT = 5012 // TCP, see TORApp/pc/tor_glasses.py (GlassesLink.download)

/**
 * The finished recordings over Wi-Fi, for the simulator PC to save next to the run's data:
 *   GET /video?name=261027_183956   -> Movies/TORApp/261027_183956.mp4 (404 while it is not there)
 * The PC fetches it (rather than the phone sending it) so the PC needs no open port of its own.
 */
class VideoServer(private val context: Context) {
  @Volatile private var server: ServerSocket? = null

  fun start() {
    if (server != null) return
    thread(name = "video-server", isDaemon = true) {
      val listening =
          try {
            ServerSocket(VIDEO_PORT)
          } catch (error: IOException) {
            Log.e(TAG, "Cannot listen on TCP $VIDEO_PORT", error)
            return@thread
          }
      server = listening
      while (!listening.isClosed) {
        val client =
            try {
              listening.accept()
            } catch (_: IOException) {
              break
            }
        thread(name = "video-send", isDaemon = true) { serve(client) }
      }
    }
  }

  fun stop() {
    server?.close()
    server = null
  }

  private fun serve(client: Socket) {
    client.use { socket ->
      try {
        val request = socket.getInputStream().bufferedReader().readLine() ?: return
        val name = Regex("""^GET /video\?name=([\w.-]+) """).find(request)?.groupValues?.get(1)
        val output = socket.getOutputStream()
        val found = name?.let { find(it) }
        if (found == null) {
          output.write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
          return
        }
        val (uri, size) = found
        output.write(
            ("HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: $size\r\n" +
                    "Connection: close\r\n\r\n")
                .toByteArray())
        context.contentResolver.openInputStream(uri)?.use { it.copyTo(output, 256 * 1024) }
        output.flush()
        Log.i(TAG, "Sent $name.mp4 ($size bytes) to ${socket.inetAddress.hostAddress}")
      } catch (error: IOException) {
        Log.w(TAG, "Send failed", error)
      }
    }
  }

  /** The finished (not pending) file Movies/TORApp/<name>.mp4 of this app, and its size. */
  private fun find(name: String): Pair<android.net.Uri, Long>? {
    val projection = arrayOf(MediaStore.Video.Media._ID, MediaStore.Video.Media.SIZE)
    val selection =
        "${MediaStore.Video.Media.DISPLAY_NAME} = ? AND ${MediaStore.Video.Media.RELATIVE_PATH} = ? AND " +
            "${MediaStore.Video.Media.IS_PENDING} = 0"
    context.contentResolver
        .query(
            MediaStore.Video.Media.EXTERNAL_CONTENT_URI, projection, selection,
            arrayOf("$name.mp4", "Movies/TORApp/"), null)
        ?.use { cursor ->
          if (!cursor.moveToFirst()) return null
          val id = cursor.getLong(0)
          return ContentUris.withAppendedId(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, id) to cursor.getLong(1)
        }
    return null
  }
}
