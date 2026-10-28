package com.drivingsim.torapp

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.RectF
import android.graphics.Typeface
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.util.Log
import android.view.Surface
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.removeCamera
import com.meta.wearable.dat.camera.types.AudioCodec
import com.meta.wearable.dat.camera.types.AudioFrame
import com.meta.wearable.dat.camera.types.AudioSampleRate
import com.meta.wearable.dat.camera.types.CameraState
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.VideoFrame
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.session.DeviceSession
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

private const val TAG = "GlassesRecorder"
private const val FRAME_RATE = 24 // one of 2, 7, 15, 24, 30
private const val VIDEO_BIT_RATE = 4_000_000
private const val AUDIO_RATE = 16_000 // the glasses' microphone, mono 16 bit PCM
private const val AUDIO_BIT_RATE = 64_000
private const val AUDIO_WAIT_US = 3_000_000L // no microphone sound this long after the video: video only
private const val CAMERA_START_TIMEOUT_MS = 10_000L
// Where the glasses display sits in the camera picture (it is in the right lens, its top edge at the
// center of the field of view), as shares of the frame: an approximation, the camera is at the left
// hinge and sees more than the display covers.
private const val OVERLAY_CENTER_X = 0.56f
private const val OVERLAY_TOP_Y = 0.5f
private const val OVERLAY_WIDTH = 0.38f

data class RecorderStatus(
    val state: String = "OFF", // OFF, STARTING, RECORDING, STOPPING, ERROR
    val name: String? = null, // the run, from the PC
    val file: String? = null, // Movies/TORApp/<name>.mp4
    val frames: Long = 0,
    val audio: Boolean = false, // microphone sound in the file
    val error: String? = null,
)

/**
 * Records the glasses' camera with what the glasses display shows drawn over it (the same image as
 * TorContent sends, added like the see-through display adds its light), and the glasses' microphone,
 * into Movies/TORApp/<name>.mp4 on the phone. The camera stream runs in the display's DeviceSession
 * (GlassesDisplay); frames come as I420, are drawn on the H.264 encoder's input surface with the
 * overlay and a clock, and the microphone's PCM goes through an AAC encoder into the same file.
 * Video and sound are stamped with System.nanoTime() when they arrive, so they stay in sync.
 */
class GlassesRecorder(private val context: Context, private val scope: CoroutineScope) {
  private val _status = MutableStateFlow(RecorderStatus())
  val status: StateFlow<RecorderStatus> = _status.asStateFlow()

  /** What the glasses show now (TorViewModel), drawn over every frame. */
  @Volatile var overlay: GlassesView = GlassesView.WAITING

  private var session: DeviceSession? = null
  private var camera: Camera? = null
  private val jobs = mutableListOf<Job>()
  @Volatile private var writer: Mp4Writer? = null
  private var uri: Uri? = null
  private var file: ParcelFileDescriptor? = null

  val active: Boolean
    get() = _status.value.state in setOf("STARTING", "RECORDING")

  /** Start recording `name` in `deviceSession` (STARTED, with the display). Main thread. */
  fun start(deviceSession: DeviceSession, name: String) {
    if (active) return
    _status.value = RecorderStatus(state = "STARTING", name = name)
    val target =
        try {
          openFile(name)
        } catch (error: Exception) {
          fail("Cannot create the video file: ${error.message}")
          return
        }
    val configuration =
        StreamConfiguration(
            AudioCodec.PCM(AudioSampleRate.RATE_16000, 1), VideoQuality.MEDIUM, FRAME_RATE, false)
    deviceSession
        .addCamera(configuration)
        .fold(
            onSuccess = { newCamera ->
              session = deviceSession
              camera = newCamera
              writer = Mp4Writer(target.fileDescriptor)
              _status.update { it.copy(file = "Movies/TORApp/$name.mp4") }
              jobs += scope.launch { run(newCamera) }
            },
            onFailure = { error, _ ->
              closeFile(keep = false)
              fail("Cannot add the camera: ${error.description}")
            },
        )
  }

  private suspend fun run(newCamera: Camera) {
    val started =
        withTimeoutOrNull(CAMERA_START_TIMEOUT_MS) {
          newCamera.state.first { it == CameraState.STARTED }
        }
    if (started == null) {
      fail("The glasses camera did not start (${newCamera.state.value})")
      stop()
      return
    }
    val stream = newCamera.stream
    jobs += scope.launch(Dispatchers.Default) { stream.videoStream.collect { onVideo(it) } }
    jobs += scope.launch(Dispatchers.Default) { stream.audioStream.collect { onAudio(it) } }
    jobs +=
        scope.launch {
          stream.errorStream.collect { error ->
            Log.e(TAG, "Stream error: $error")
            _status.update { it.copy(error = error.toString()) }
          }
        }
    stream
        .start()
        .onSuccess {
          _status.update { it.copy(state = "RECORDING") }
          Log.i(TAG, "Recording ${_status.value.file}")
        }
        .onFailure { error, _ ->
          fail("The camera stream did not start: $error")
          stop()
        }
  }

  /** Stop and finish the file (it shows in the gallery). Main thread; safe to call when off. */
  fun stop() {
    val current = session
    if (_status.value.state == "OFF" || _status.value.state == "STOPPING") return
    val failed = _status.value.state == "ERROR"
    _status.update { it.copy(state = "STOPPING") }
    jobs.forEach { it.cancel() }
    jobs.clear()
    try {
      camera?.stream?.stop()
      camera?.stop()
    } catch (error: Exception) {
      Log.w(TAG, "Camera stop failed", error)
    }
    current?.removeCamera()
    camera = null
    session = null
    val finishing = writer
    writer = null
    // a thread of its own, not the scope: the file is finished also when the app closes
    Thread(
            {
              val frames = finishing?.finish() ?: 0
              closeFile(keep = frames > 0)
              _status.update {
                it.copy(
                    state = if (failed) "ERROR" else "OFF", frames = frames, audio = finishing?.hasAudio == true)
              }
              Log.i(TAG, "Recording stopped: $frames frames")
            },
            "recorder-finish")
        .start()
  }

  private fun onVideo(frame: VideoFrame) {
    val current = writer ?: return
    if (current.drawFrame(frame, overlay)) _status.update { it.copy(frames = current.frames) }
  }

  private fun onAudio(frame: AudioFrame) {
    writer?.writeAudio(frame.buffer)
  }

  /** `name` cannot be recorded (e.g. no glasses session): an error until the next run's name. */
  fun refuse(name: String, message: String) {
    _status.value = RecorderStatus(state = "ERROR", name = name, error = message)
    Log.e(TAG, message)
  }

  private fun fail(message: String) {
    Log.e(TAG, message)
    _status.update { it.copy(state = "ERROR", error = message) }
  }

  private fun openFile(name: String): ParcelFileDescriptor {
    val values =
        ContentValues().apply {
          put(MediaStore.Video.Media.DISPLAY_NAME, "$name.mp4")
          put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
          put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/TORApp")
          put(MediaStore.Video.Media.IS_PENDING, 1)
        }
    val resolver = context.contentResolver
    val newUri =
        resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("MediaStore insert failed")
    uri = newUri
    return (resolver.openFileDescriptor(newUri, "rw") ?: throw IllegalStateException("no file"))
        .also { file = it }
  }

  private fun closeFile(keep: Boolean) {
    try {
      file?.close()
    } catch (_: Exception) {}
    file = null
    val current = uri ?: return
    uri = null
    val resolver = context.contentResolver
    if (keep) {
      resolver.update(current, ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }, null, null)
    } else {
      resolver.delete(current, null, null)
    }
  }
}

/**
 * H.264 + AAC into one MP4. The video encoder is made with the first frame's size; frames are drawn
 * on its input surface. The muxer starts once both tracks are known (or the video alone after
 * AUDIO_WAIT_US without sound); samples from before are dropped, the video then starts at a key frame.
 *
 * Three locks, so the slow drawing of a frame never holds up the sound or the file: drawLock (the
 * video encoder's input), audioLock (the sound encoder's input), muxLock (the muxer).
 */
private class Mp4Writer(fd: java.io.FileDescriptor) {
  private val muxer = MediaMuxer(fd, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
  private val drawLock = Object()
  private val audioLock = Object()
  private val muxLock = Object()
  @Volatile private var video: MediaCodec? = null
  private var surface: Surface? = null
  @Volatile private var audio: MediaCodec? = null
  private var videoTrack = -1
  private var audioTrack = -1
  @Volatile private var muxing = false
  private var waitingForKey = true
  private var firstVideoUs = -1L
  private var lastAudioUs = -1L
  @Volatile var frames = 0L
    private set
  @Volatile var hasAudio = false
    private set
  @Volatile private var finished = false
  private var drainer: Thread? = null

  private var bitmap: Bitmap? = null
  private var yuv = ByteArray(0)
  private var pixels = IntArray(0)
  private var shownView: GlassesView? = null
  private var shownImage: Bitmap? = null
  private val additive = Paint(Paint.FILTER_BITMAP_FLAG).apply { xfermode = PorterDuffXfermode(PorterDuff.Mode.ADD) }
  private val clockPaint =
      Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        typeface = Typeface.MONOSPACE
        setShadowLayer(3f, 1f, 1f, Color.BLACK)
      }
  private val clock = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)

  /** Draws one camera frame with the overlay; false if it could not be used. */
  fun drawFrame(frame: VideoFrame, view: GlassesView): Boolean {
    val width = frame.width
    val height = frame.height
    val buffer = frame.buffer
    if (buffer.remaining() < width * height * 3 / 2) {
      Log.w(TAG, "Frame ${width}x$height: ${buffer.remaining()} bytes, not I420")
      return false
    }
    synchronized(drawLock) {
      if (finished) return false
      if (video == null) startVideo(width, height)
      val target = surface ?: return false
      val picture = toBitmap(buffer, width, height)
      val canvas = target.lockHardwareCanvas()
      try {
        canvas.drawBitmap(picture, 0f, 0f, null)
        overlayImage(view)?.let { image ->
          val w = width * OVERLAY_WIDTH
          val left = width * OVERLAY_CENTER_X - w / 2
          val top = height * OVERLAY_TOP_Y
          canvas.drawBitmap(image, null, RectF(left, top, left + w, top + w), additive)
        }
        clockPaint.textSize = height * 0.025f
        canvas.drawText(clock.format(Date()), width * 0.02f, height * 0.04f, clockPaint)
      } finally {
        target.unlockCanvasAndPost(canvas)
      }
      frames++
    }
    return true
  }

  /** The glasses' image of `view` (made again only when the view changes); null: nothing shown. */
  private fun overlayImage(view: GlassesView): Bitmap? {
    if (view.mode == TorMode.OFF || view.test != null) return null
    if (view != shownView) {
      shownView = view
      shownImage = glassesImage(view)
    }
    return shownImage
  }

  private fun toBitmap(buffer: java.nio.ByteBuffer, width: Int, height: Int): Bitmap {
    val current =
        bitmap?.takeIf { it.width == width && it.height == height }
            ?: Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).also { bitmap = it }
    val ySize = width * height
    val size = ySize * 3 / 2
    if (yuv.size != size) yuv = ByteArray(size)
    if (pixels.size != ySize) pixels = IntArray(ySize)
    buffer.duplicate().get(yuv, 0, size) // one copy: indexing a direct ByteBuffer per pixel is slow
    val uStart = ySize
    val vStart = uStart + ySize / 4
    val half = width / 2
    for (y in 0 until height) {
      val row = y * width
      val chroma = (y / 2) * half
      for (x in 0 until width) {
        val luma = (yuv[row + x].toInt() and 0xff) - 16
        val u = (yuv[uStart + chroma + x / 2].toInt() and 0xff) - 128
        val v = (yuv[vStart + chroma + x / 2].toInt() and 0xff) - 128
        val c = 1192 * luma.coerceAtLeast(0)
        val r = ((c + 1634 * v) shr 10).coerceIn(0, 255)
        val g = ((c - 833 * v - 400 * u) shr 10).coerceIn(0, 255)
        val b = ((c + 2066 * u) shr 10).coerceIn(0, 255)
        pixels[row + x] = (0xff shl 24) or (r shl 16) or (g shl 8) or b
      }
    }
    current.setPixels(pixels, 0, width, 0, 0, width, height)
    return current
  }

  private fun startVideo(width: Int, height: Int) {
    val format =
        MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
          setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
          setInteger(MediaFormat.KEY_BIT_RATE, VIDEO_BIT_RATE)
          setInteger(MediaFormat.KEY_FRAME_RATE, FRAME_RATE)
          setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
        }
    val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
    codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
    surface = codec.createInputSurface()
    codec.start()
    video = codec
    drainer = Thread({ drainLoop() }, "recorder-drain").apply { start() }
    Log.i(TAG, "Video ${width}x$height at $FRAME_RATE fps")
  }

  private fun startAudio() {
    val format =
        MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, AUDIO_RATE, 1).apply {
          setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
          setInteger(MediaFormat.KEY_BIT_RATE, AUDIO_BIT_RATE)
          setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16_384)
        }
    val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
    codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
    codec.start()
    audio = codec
  }

  /** 16 bit mono PCM from the glasses' microphone. */
  fun writeAudio(pcm: java.nio.ByteBuffer) {
    synchronized(audioLock) {
      if (finished || video == null) return // sound only once there is a picture
      if (audio == null) {
        if (muxing) return // started as video only
        startAudio()
      }
      val codec = audio ?: return
      val bytes = pcm.remaining()
      // stamped at its arrival, less its own length, on the clock of the video surface
      var timeUs = System.nanoTime() / 1000 - bytes / 2 * 1_000_000L / AUDIO_RATE
      if (timeUs <= lastAudioUs) timeUs = lastAudioUs + 1
      while (pcm.hasRemaining()) {
        val index = codec.dequeueInputBuffer(5_000)
        if (index < 0) return // the encoder is behind: drop the rest
        val input = codec.getInputBuffer(index) ?: return
        val count = minOf(input.remaining(), pcm.remaining())
        val slice = pcm.duplicate().apply { limit(position() + count) }
        input.put(slice)
        pcm.position(pcm.position() + count)
        codec.queueInputBuffer(index, 0, count, timeUs, 0)
        lastAudioUs = timeUs
        timeUs += count / 2 * 1_000_000L / AUDIO_RATE
      }
    }
  }

  private fun drainLoop() {
    val info = MediaCodec.BufferInfo()
    var videoDone = false
    var audioDone = false
    while (!(videoDone && (audioDone || audio == null))) {
      if (!videoDone) videoDone = drain(video ?: break, info, isVideo = true)
      audio?.let { if (!audioDone) audioDone = drain(it, info, isVideo = false) }
      if (!finished) Thread.sleep(2)
    }
  }

  /** Moves what `codec` has encoded into the muxer; true at its end of stream. */
  private fun drain(codec: MediaCodec, info: MediaCodec.BufferInfo, isVideo: Boolean): Boolean {
    while (true) {
      val index = codec.dequeueOutputBuffer(info, if (finished) 10_000 else 0)
      when {
        index == MediaCodec.INFO_TRY_AGAIN_LATER -> return false
        index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED ->
            synchronized(muxLock) {
              if (isVideo) videoTrack = muxer.addTrack(codec.outputFormat)
              else if (!muxing) audioTrack = muxer.addTrack(codec.outputFormat)
              startMuxer()
            }
        index >= 0 -> {
          val data = codec.getOutputBuffer(index)
          val end = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
          val config = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
          if (data != null && info.size > 0 && !config) write(data, info, isVideo)
          codec.releaseOutputBuffer(index, false)
          if (end) return true
        }
      }
    }
  }

  /** Under muxLock. */
  private fun startMuxer() {
    if (muxing || videoTrack < 0) return
    if (audioTrack < 0 && audio != null) return // wait for the sound's format
    muxer.start()
    muxing = true
    hasAudio = audioTrack >= 0
    video?.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0) })
  }

  private fun write(data: java.nio.ByteBuffer, info: MediaCodec.BufferInfo, isVideo: Boolean) {
    synchronized(muxLock) {
      if (!muxing) {
        // no sound yet a while after the first frame: video only
        if (isVideo) {
          if (firstVideoUs < 0) firstVideoUs = info.presentationTimeUs
          if (audio == null && info.presentationTimeUs - firstVideoUs > AUDIO_WAIT_US) startMuxer()
        }
        if (!muxing) return
      }
      if (isVideo) {
        if (waitingForKey && info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME == 0) return
        waitingForKey = false
        muxer.writeSampleData(videoTrack, data, info)
      } else if (audioTrack >= 0 && !waitingForKey) {
        muxer.writeSampleData(audioTrack, data, info)
      }
    }
  }

  /** Ends both streams and closes the file; the number of frames drawn. */
  fun finish(): Long {
    if (finished) return frames
    finished = true
    synchronized(drawLock) { video?.signalEndOfInputStream() } // after the frame being drawn
    synchronized(audioLock) {
      audio?.let { codec ->
        val index = codec.dequeueInputBuffer(10_000)
        if (index >= 0) {
          codec.queueInputBuffer(index, 0, 0, lastAudioUs + 1, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
        }
      }
    }
    drainer?.join(5_000)
    for (codec in listOfNotNull(video, audio)) {
      try {
        codec.stop()
      } catch (_: IllegalStateException) {}
      codec.release()
    }
    surface?.release()
    synchronized(muxLock) {
      try {
        if (muxing) muxer.stop()
      } catch (error: IllegalStateException) {
        Log.e(TAG, "Muxer stop failed", error)
      }
      muxer.release()
    }
    return frames
  }
}
