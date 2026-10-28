package com.drivingsim.torapp

import android.util.Log
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.DeviceSessionError
import com.meta.wearable.dat.display.Display
import com.meta.wearable.dat.display.addDisplay
import com.meta.wearable.dat.display.removeDisplay
import com.meta.wearable.dat.display.types.DisplayState
import com.meta.wearable.dat.display.views.ContentScope
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val TAG = "GlassesDisplay"

data class GlassesState(
    val sessionState: DeviceSessionState? = null,
    val displayState: DisplayState? = null,
    val error: String? = null,
    val datAppUpdateRequired: Boolean = false,
) {
  val active: Boolean
    get() = sessionState != null && sessionState != DeviceSessionState.STOPPED
}

/**
 * DAT session with the display capability on the Meta Ray-Ban Display glasses (the DisplayAccess
 * sample's flow): create session -> STARTED -> addDisplay -> DisplayState.STARTED -> sendContent.
 * start() and stop() run on the main thread (scope: viewModelScope).
 */
class GlassesDisplay(private val scope: CoroutineScope) {
  private val _state = MutableStateFlow(GlassesState())
  val state: StateFlow<GlassesState> = _state.asStateFlow()

  private var session: DeviceSession? = null
  @Volatile private var display: Display? = null

  /** The running session (STARTED), for the camera of the recording; null otherwise. */
  val startedSession: DeviceSession?
    get() = session?.takeIf { _state.value.sessionState == DeviceSessionState.STARTED }
  private val jobs = mutableListOf<Job>()

  fun start() {
    if (session != null) return
    _state.value = GlassesState()
    Wearables.createSession(AutoDeviceSelector(filter = { it.isDisplayCapable() }))
        .fold(
            onSuccess = { newSession ->
              session = newSession
              jobs += scope.launch { newSession.state.collect { onSessionState(newSession, it) } }
              jobs +=
                  scope.launch {
                    newSession.errors.collect { error ->
                      Log.e(TAG, "Session error: ${error.description}")
                      _state.update {
                        it.copy(
                            error = error.description,
                            datAppUpdateRequired =
                                it.datAppUpdateRequired ||
                                    error == DeviceSessionError.DAT_APP_ON_THE_GLASSES_UPDATE_REQUIRED,
                        )
                      }
                    }
                  }
              newSession.start()
            },
            onFailure = { error, _ ->
              Log.e(TAG, "Failed to create session: ${error.description}")
              _state.update {
                it.copy(
                    error = error.description,
                    datAppUpdateRequired =
                        error == DeviceSessionError.DAT_APP_ON_THE_GLASSES_UPDATE_REQUIRED,
                )
              }
            },
        )
  }

  fun stop() {
    val current = session ?: return
    current.removeDisplay()
    current.stop()
    release()
  }

  /** Replaces everything on the glasses display. False if the display is not ready or it failed. */
  suspend fun send(content: ContentScope.() -> Unit): Boolean {
    val current = display ?: return false
    if (_state.value.displayState != DisplayState.STARTED) return false
    var sent = false
    current
        .sendContent(content)
        .onSuccess { sent = true }
        .onFailure { error, _ ->
          Log.w(TAG, "Send failed: ${error.description}")
          _state.update { it.copy(error = error.description) }
        }
    return sent
  }

  private fun onSessionState(newSession: DeviceSession, sessionState: DeviceSessionState) {
    Log.i(TAG, "Session state: $sessionState")
    _state.update { it.copy(sessionState = sessionState) }
    when (sessionState) {
      DeviceSessionState.STARTED -> if (display == null) attachDisplay(newSession)
      DeviceSessionState.STOPPED -> release() // terminal: start() creates a new session
      else -> Unit
    }
  }

  private fun attachDisplay(newSession: DeviceSession) {
    newSession
        .addDisplay()
        .fold(
            onSuccess = { newDisplay ->
              display = newDisplay
              jobs +=
                  scope.launch {
                    newDisplay.state.collect { displayState ->
                      Log.i(TAG, "Display state: $displayState")
                      _state.update { it.copy(displayState = displayState) }
                    }
                  }
            },
            onFailure = { error, _ ->
              Log.e(TAG, "Failed to attach display: ${error.description}")
              _state.update { it.copy(error = error.description) }
            },
        )
  }

  private fun release() {
    jobs.forEach { it.cancel() }
    jobs.clear()
    display = null
    session = null
    _state.update { it.copy(sessionState = DeviceSessionState.STOPPED, displayState = null) }
  }
}
