package com.drivingsim.torapp

import kotlin.math.ceil
import org.json.JSONException
import org.json.JSONObject

/** Test screens of the phone's Test buttons. */
enum class DisplayTest {
  AREA, // 600x600 frame and grid: what part of the display is visible
  TEXT, // native text lines: how much text fits before it scrolls
}

enum class TorMode {
  AUTO,
  PRE_ALERT,
  TOR,
  MANUAL,
  OFF,
}

/** One packet from the simulator PC (TORApp/pc/tor_glasses.py). */
data class TorState(
    val seq: Int,
    val mode: TorMode,
    val message: String,
    val remaining: Double?,
    val total: Double?,
    val label: String, // mode box text of the simulator screen, "" for the default
) {
  companion object {
    fun parse(text: String): TorState? =
        try {
          val json = JSONObject(text)
          TorState(
              seq = json.getInt("seq"),
              mode = TorMode.valueOf(json.getString("mode")),
              message = json.optString("message", ""),
              remaining = if (json.isNull("remaining")) null else json.getDouble("remaining"),
              total = if (json.isNull("total")) null else json.getDouble("total"),
              label = json.optString("label", ""),
          )
        } catch (_: JSONException) {
          null
        } catch (_: IllegalArgumentException) { // unknown mode
          null
        }
  }
}

/**
 * What the glasses show. Two equal views look the same, so a new view is sent to the glasses only
 * when the mode, the message or the whole seconds of the countdown change.
 *
 * seq: the PC's seq of the state shown, reported back to the PC; -1 for the phone's test buttons.
 */
data class GlassesView(
    val seq: Int,
    val mode: TorMode,
    val message: String = "",
    val seconds: Int? = null,
    val total: Double? = null,
    val label: String = "",
    val dim: Boolean = false, // TOR banner in its dark flash color (blink test)
    val test: DisplayTest? = null,
) {
  companion object {
    val WAITING = GlassesView(seq = -1, mode = TorMode.OFF)
  }
}

fun TorState.toView() =
    GlassesView(seq, mode, message, remaining?.let { ceil(it).toInt().coerceAtLeast(0) }, total, label)
