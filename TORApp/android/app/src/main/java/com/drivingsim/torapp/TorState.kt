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

/**
 * NDRT ready-to-resume summary of the notice draft (_Experiment/kakao_ndrt.py): the
 * latest request and its result. Only sent while the experiment runs the NDRT summary condition.
 */
data class RtrStatus(
    val id: Int,
    val state: String, // idle, pending, done, error, timeout
    val source: String, // auto (5 s before the pre-alert), prealert, glasses, extension, ...
    val lines: List<String>,
    val error: String,
) {
  companion object {
    fun parse(json: JSONObject?): RtrStatus? =
        json?.let {
          RtrStatus(
              id = it.optInt("id"),
              state = it.optString("state", "idle"),
              source = it.optString("source", ""),
              lines = it.optJSONArray("lines")?.let { a -> List(a.length()) { i -> a.optString(i) } } ?: emptyList(),
              error = it.optString("error", ""),
          )
        }
  }
}

/** One packet from the simulator PC (TORApp/pc/tor_glasses.py). */
data class TorState(
    val seq: Int,
    val mode: TorMode,
    val message: String,
    val remaining: Double?,
    val total: Double?,
    val label: String, // mode box text of the simulator screen, "" for the default
    val text: List<String>, // intervention lines under the PRE-ALERT banner
    val rtr: RtrStatus?, // null: the PC does not use the RtR summary
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
              text =
                  json.optJSONArray("text")?.let { lines ->
                    List(lines.length()) { lines.optString(it) }.filter { it.isNotBlank() }
                  } ?: emptyList(),
              rtr = RtrStatus.parse(json.optJSONObject("rtr")),
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
    val text: List<String> = emptyList(), // intervention lines under the PRE-ALERT banner
    val dim: Boolean = false, // TOR banner in its dark flash color (blink test)
    val test: DisplayTest? = null,
) {
  companion object {
    val WAITING = GlassesView(seq = -1, mode = TorMode.OFF)
  }
}

fun TorState.toView() =
    GlassesView(
        seq, mode, message, remaining?.let { ceil(it).toInt().coerceAtLeast(0) }, total, label, text)
