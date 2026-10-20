package com.drivingsim.torapp

import android.util.Log
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketAddress
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private const val TAG = "TorReceiver"

/** Receives the takeover state from the simulator PC over UDP and answers each packet. */
class TorReceiver(private val port: Int) {
  @Volatile private var socket: DatagramSocket? = null
  @Volatile private var sender: SocketAddress? = null

  /** onPacket runs on an IO thread and returns the answer sent back to the PC. */
  fun start(scope: CoroutineScope, onPacket: (TorState) -> String, onError: (String) -> Unit) {
    scope.launch(Dispatchers.IO) {
      val address = InetSocketAddress(port) // outside apply: there `port` is the socket's own (-1)
      val listening =
          try {
            DatagramSocket(null).apply {
              reuseAddress = true
              bind(address)
            }
          } catch (error: IOException) {
            Log.e(TAG, "Cannot listen on UDP $port", error)
            onError("Cannot listen on UDP $port: ${error.message}")
            return@launch
          }
      socket = listening
      val buffer = ByteArray(2048)
      try {
        while (isActive) {
          val packet = DatagramPacket(buffer, buffer.size)
          listening.receive(packet)
          val text = String(packet.data, packet.offset, packet.length, Charsets.UTF_8)
          val state = TorState.parse(text) ?: continue
          sender = packet.socketAddress
          send(listening, onPacket(state), packet.socketAddress)
        }
      } catch (error: IOException) {
        if (!listening.isClosed) Log.e(TAG, "UDP receive failed", error)
      } finally {
        listening.close()
      }
    }
  }

  /** Extra answer to the last sender, right when a new state is on the glasses (latency). */
  fun reply(text: String) {
    val current = socket ?: return
    val to = sender ?: return
    try {
      send(current, text, to)
    } catch (error: IOException) {
      Log.w(TAG, "UDP reply failed", error)
    }
  }

  fun stop() {
    socket?.close()
  }

  private fun send(socket: DatagramSocket, text: String, to: SocketAddress) {
    val bytes = text.toByteArray(Charsets.UTF_8)
    socket.send(DatagramPacket(bytes, bytes.size, to))
  }
}
