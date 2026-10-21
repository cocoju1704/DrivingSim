package com.drivingsim.torapp

import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioTrack
import android.util.Log
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.sin

private const val TAG = "AlertSounds"
private const val RATE = 48_000
private const val CHUNK = RATE / 100 // 10 ms per write

/**
 * The simulator's alert sounds (takeover_experiment.py AlertSound), played by the phone. The
 * glasses are the phone's Bluetooth audio device, so the sounds come from their speakers.
 *
 * The track plays silence all the time: a Bluetooth audio link that starts with the sound would
 * cut off its start or delay it, so the link stays open and the sounds are mixed in.
 */
class AlertSounds(private val onOutput: (String?) -> Unit) {
  // (Hz, s) parts and volume as in AlertSound: chime for the pre-alert, beeps for the TOR, click
  private val chime = tone(listOf(880.0 to 0.18, 0.0 to 0.06, 1175.0 to 0.30), 0.5)
  private val beeps = tone(listOf(1000.0 to 0.15, 0.0 to 0.08, 1000.0 to 0.15, 0.0 to 0.45), 0.7)
  private val click = tone(listOf(660.0 to 0.10), 0.4)

  private class Request(val pcm: ShortArray?, val loop: Boolean)

  private val request = AtomicReference<Request?>(null)
  @Volatile private var running = true
  @Volatile
  var enabled = true
    set(value) {
      field = value
      if (!value) stop()
    }
  private var mode = TorMode.OFF

  private val track =
      AudioTrack.Builder()
          .setAudioAttributes(
              AudioAttributes.Builder()
                  .setUsage(AudioAttributes.USAGE_MEDIA) // media goes to the Bluetooth headset
                  .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                  .build())
          .setAudioFormat(
              AudioFormat.Builder()
                  .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                  .setSampleRate(RATE)
                  .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                  .build())
          .setTransferMode(AudioTrack.MODE_STREAM)
          .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
          .setBufferSizeInBytes(
              AudioTrack.getMinBufferSize(
                  RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT))
          .build()

  private val writer =
      Thread({ write() }, "alert-sounds").apply {
        priority = Thread.MAX_PRIORITY
        start()
      }

  init {
    track.addOnRoutingChangedListener({ onOutput(describe(it.routedDevice)) }, null)
    track.play()
    onOutput(describe(track.routedDevice))
  }

  /** Sounds for a change of mode, as the simulator plays them. */
  fun onMode(next: TorMode) {
    val previous = mode
    mode = next
    if (next == previous) return
    when (next) {
      TorMode.PRE_ALERT -> play(chime) // also ends the beeps
      TorMode.TOR -> play(beeps, loop = true)
      TorMode.MANUAL ->
          if (previous == TorMode.PRE_ALERT || previous == TorMode.TOR) play(click) else stop()
      TorMode.AUTO,
      TorMode.OFF -> stop()
    }
  }

  fun release() {
    running = false
    writer.join(500)
    track.release()
  }

  private fun play(pcm: ShortArray, loop: Boolean = false) {
    request.set(Request(if (enabled) pcm else null, loop))
  }

  private fun stop() = request.set(Request(null, false))

  private fun write() {
    val chunk = ShortArray(CHUNK)
    var playing: ShortArray? = null
    var loop = false
    var position = 0
    while (running) {
      request.getAndSet(null)?.let {
        playing = it.pcm
        loop = it.loop
        position = 0
      }
      chunk.fill(0)
      var filled = 0
      while (filled < CHUNK) {
        val pcm = playing ?: break
        val count = min(CHUNK - filled, pcm.size - position)
        pcm.copyInto(chunk, filled, position, position + count)
        filled += count
        position += count
        if (position >= pcm.size) {
          position = 0
          if (!loop) playing = null
        }
      }
      if (track.write(chunk, 0, CHUNK) < 0) {
        Log.e(TAG, "AudioTrack write failed")
        return
      }
    }
  }

  private fun tone(parts: List<Pair<Double, Double>>, volume: Double): ShortArray {
    val pieces =
        parts.map { (frequency, seconds) ->
          val count = (RATE * seconds).toInt()
          val edge = min(count / 2, RATE / 100) // 10 ms fade in/out, no clicks
          ShortArray(count) { i ->
            if (frequency == 0.0) return@ShortArray 0
            var value = sin(2.0 * PI * frequency * i / RATE)
            if (i < edge) value *= i.toDouble() / edge
            if (i >= count - edge) value *= (count - 1 - i).toDouble() / edge
            (value * volume * Short.MAX_VALUE).toInt().toShort()
          }
        }
    return pieces.reduce { all, piece -> all + piece }
  }

  private fun describe(device: AudioDeviceInfo?): String? {
    device ?: return null
    val kind =
        when (device.type) {
          AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
          AudioDeviceInfo.TYPE_BLE_HEADSET,
          AudioDeviceInfo.TYPE_BLE_SPEAKER -> "Bluetooth"
          AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "Bluetooth call"
          AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "phone speaker"
          else -> "type ${device.type}"
        }
    return "${device.productName} ($kind)"
  }
}
