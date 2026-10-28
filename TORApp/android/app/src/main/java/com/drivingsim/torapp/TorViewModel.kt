package com.drivingsim.torapp

import android.app.Activity
import android.app.Application
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.wifi.WifiManager
import android.os.SystemClock
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.Device
import com.meta.wearable.dat.core.types.DeviceCompatibility
import com.meta.wearable.dat.core.types.DeviceIdentifier
import com.meta.wearable.dat.core.types.LinkState
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.meta.wearable.dat.core.types.RegistrationState
import com.meta.wearable.dat.display.types.DisplayState
import java.net.Inet4Address
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject

private const val TAG = "TORApp"
const val TOR_PORT = 5007 // UDP, see TORApp/pc/tor_glasses.py
private const val KEEP_AWAKE_MS = 15_000L // the glasses display dims after 20 s without activity
private const val TOR_BLINK_MS = 250L // the TOR message on, then off, this long each (2 blinks per second)
private const val RECORD_SILENCE_MS = 10_000L // no packet from the PC this long: the recording stops

data class UiState(
    val registrationState: RegistrationState = RegistrationState.UNAVAILABLE,
    val glassesConnected: Boolean = false,
    val firmwareUpdateRequired: Boolean = false,
    val glasses: GlassesState = GlassesState(),
    val phoneAddress: String? = null,
    val receiveError: String? = null,
    val registrationError: String? = null,
    val lastState: TorState? = null,
    val lastPacketAt: Long = 0L, // SystemClock.elapsedRealtime()
    val packets: Long = 0L,
    val shownView: GlassesView? = null,
    val keepAwake: Boolean = true,
    val lastSendMs: Long? = null, // duration of the last sendContent (Bluetooth)
    val blinking: Boolean = false,
    val alertSounds: Boolean = false, // off: the alert sounds come from the simulator PC only
    val audioOutput: String? = null, // where the sounds play: the glasses when they are connected
    val rtrPresses: Int = 0, // RtR button presses since the app started
    val recording: RecorderStatus = RecorderStatus(),
    val cameraAllowed: Boolean? = null, // the glasses' camera and microphone (null: not checked yet)
    val microphoneAllowed: Boolean? = null,
)

class TorViewModel(application: Application) : AndroidViewModel(application) {
  private val _uiState = MutableStateFlow(UiState())
  val uiState: StateFlow<UiState> = _uiState.asStateFlow()

  private val glasses = GlassesDisplay(viewModelScope)
  private val receiver = TorReceiver(TOR_PORT)
  private val wanted = MutableStateFlow(GlassesView.WAITING) // what the glasses should show
  private val sounds = AlertSounds { output -> _uiState.update { it.copy(audioOutput = output) } }
  private val recorder = GlassesRecorder(application, viewModelScope)
  private val videoServer = VideoServer(application).apply { start() } // the PC fetches the recordings
  private val sendLock = Mutex()
  @Volatile private var lastSentAt = 0L
  @Volatile private var shownSeq = -1
  @Volatile private var lastSeq = -1 // seq of the PC's last packet
  // Sent in every answer: the PC requests a summary for each increase (lost answers do not matter).
  private val rtrPresses = AtomicInteger(0)

  private var observing = false
  private val metadataJobs = mutableMapOf<DeviceIdentifier, Job>()
  private val devices = MutableStateFlow<Map<DeviceIdentifier, Device>>(emptyMap())

  // Wi-Fi power saving holds packets back by up to a few hundred ms: keep the radio awake.
  private val wifiLock =
      application
          .getSystemService(WifiManager::class.java)
          .createWifiLock(WifiManager.WIFI_MODE_FULL_LOW_LATENCY, TAG)
          .apply { setReferenceCounted(false) }
  private val connectivity = application.getSystemService(ConnectivityManager::class.java)
  private val networkCallback =
      object : ConnectivityManager.NetworkCallback() {
        override fun onLinkPropertiesChanged(network: Network, properties: LinkProperties) {
          val address =
              properties.linkAddresses
                  .map { it.address }
                  .firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
                  ?.hostAddress
          _uiState.update { it.copy(phoneAddress = address) }
        }

        override fun onLost(network: Network) {
          _uiState.update { it.copy(phoneAddress = null) }
        }
      }

  init {
    wifiLock.acquire()
    connectivity.registerDefaultNetworkCallback(networkCallback)
    receiver.start(
        viewModelScope,
        onPacket = ::onPacket,
        onError = { message -> _uiState.update { it.copy(receiveError = message) } },
    )
    viewModelScope.launch { glasses.state.collect { state -> _uiState.update { it.copy(glasses = state) } } }
    // The alert sounds follow the mode right away, independent of the display's Bluetooth sends.
    viewModelScope.launch(Dispatchers.Default) {
      wanted.collect {
        sounds.onMode(it.mode)
        recorder.overlay = it // the recording draws what the glasses show
      }
    }
    viewModelScope.launch { recorder.status.collect { status -> _uiState.update { it.copy(recording = status) } } }
    // The TOR message blinks: on and off TOR_BLINK_MS each, until the mode changes.
    viewModelScope.launch {
      while (isActive) {
        delay(TOR_BLINK_MS)
        wanted.update { if (it.mode == TorMode.TOR && it.test == null) it.copy(dim = !it.dim) else it }
      }
    }

    // Send the wanted view when it changes, and again when the display (re)starts.
    viewModelScope.launch(Dispatchers.IO) {
      combine(wanted, glasses.state.map { it.displayState }.distinctUntilChanged()) { view, display ->
            view to display
          }
          .conflate() // a slow Bluetooth send skips views that are already out of date
          .collect { (view, display) -> if (display == DisplayState.STARTED) show(view) }
    }
    viewModelScope.launch(Dispatchers.IO) {
      while (isActive) {
        delay(1_000)
        // the PC is gone (it ended without saying so): finish the recording
        if (recorder.active && SystemClock.elapsedRealtime() - _uiState.value.lastPacketAt > RECORD_SILENCE_MS) {
          launch(Dispatchers.Main) { recorder.stop() }
        }
        if (
            _uiState.value.keepAwake &&
                glasses.state.value.displayState == DisplayState.STARTED &&
                SystemClock.elapsedRealtime() - lastSentAt > KEEP_AWAKE_MS
        ) {
          show(wanted.value)
        }
      }
    }
  }

  /** After the Android permissions: start the SDK and follow registration and devices. */
  fun startObserving() {
    if (observing) return
    observing = true
    Wearables.initialize(getApplication())
    viewModelScope.launch {
      Wearables.registrationState.collect { state ->
        _uiState.update { it.copy(registrationState = state) }
        if (state == RegistrationState.REGISTERED) checkGlassesPermissions()
      }
    }
    viewModelScope.launch {
      Wearables.registrationErrorStream.collect { error ->
        val message = error.getLocalizedDescription(getApplication())
        Log.e(TAG, "Registration error: $message")
        _uiState.update { it.copy(registrationError = message) }
      }
    }
    viewModelScope.launch {
      Wearables.devices.collect { ids ->
        (metadataJobs.keys - ids).forEach { removed ->
          metadataJobs.remove(removed)?.cancel()
          devices.update { it - removed }
        }
        ids.forEach { id ->
          metadataJobs.getOrPut(id) {
            launch {
              Wearables.devicesMetadata[id]?.collect { device ->
                devices.update { it + (id to device) }
              }
            }
          }
        }
      }
    }
    viewModelScope.launch {
      devices.collect { all ->
        _uiState.update {
          it.copy(
              glassesConnected =
                  all.values.any { device ->
                    device.linkState == LinkState.CONNECTED && device.isDisplayCapable()
                  },
              firmwareUpdateRequired =
                  all.values.any { device ->
                    device.compatibility == DeviceCompatibility.DEVICE_UPDATE_REQUIRED
                  },
          )
        }
      }
    }
  }

  /** Whether the app may use the glasses' camera and microphone (for the recording). */
  fun checkGlassesPermissions() {
    viewModelScope.launch {
      suspend fun allowed(permission: Permission): Boolean {
        var granted = false
        Wearables.checkPermissionStatus(permission).onSuccess { granted = it is PermissionStatus.Granted }
        return granted
      }
      val camera = allowed(Permission.CAMERA)
      val microphone = allowed(Permission.MICROPHONE)
      _uiState.update { it.copy(cameraAllowed = camera, microphoneAllowed = microphone) }
    }
  }

  fun register(activity: Activity) = Wearables.startRegistration(activity)

  fun unregister(activity: Activity) = Wearables.startUnregistration(activity)

  fun openFirmwareUpdate(activity: Activity) {
    Wearables.openFirmwareUpdate(activity)
  }

  fun openDatAppUpdate(activity: Activity) {
    Wearables.openDATGlassesAppUpdate(activity)
  }

  fun startGlasses() = glasses.start()

  fun stopGlasses() = glasses.stop()

  fun setKeepAwake(enabled: Boolean) = _uiState.update { it.copy(keepAwake = enabled) }

  fun setAlertSounds(enabled: Boolean) {
    sounds.enabled = enabled
    _uiState.update { it.copy(alertSounds = enabled) }
  }

  /** Test buttons: show a mode without the PC (the PC's next packet replaces it). */
  fun test(mode: TorMode) {
    wanted.value =
        when (mode) {
          TorMode.PRE_ALERT -> GlassesView(-1, mode, "곧 자율주행 구간이 끝납니다")
          TorMode.TOR -> GlassesView(-1, mode, "지금 직접 운전하세요")
          else -> GlassesView(-1, mode)
        }
  }

  /** RtR button: ask the PC for the participant's NDRT ready-to-resume summary now. */
  fun requestRtr() {
    val presses = rtrPresses.incrementAndGet()
    _uiState.update { it.copy(rtrPresses = presses) }
    viewModelScope.launch(Dispatchers.IO) { receiver.reply(answer(lastSeq)) } // right away, not at the next packet
  }

  fun testDisplay(test: DisplayTest) {
    wanted.value = GlassesView(-1, TorMode.OFF, test = test)
  }

  /** TOR banner switching between its bright and dark red, like the screen's flashing banner. */
  fun testBlink(periodMs: Long) {
    if (_uiState.value.blinking) return
    _uiState.update { it.copy(blinking = true) }
    viewModelScope.launch {
      val end = SystemClock.elapsedRealtime() + 6_000
      var dim = false
      while (SystemClock.elapsedRealtime() < end) {
        val seconds = ((end - SystemClock.elapsedRealtime()) / 1000 + 1).toInt()
        wanted.value = GlassesView(-1, TorMode.TOR, "지금 직접 운전하세요", seconds, 6.0, dim = dim)
        dim = !dim
        delay(periodMs)
      }
      wanted.value = GlassesView(-1, TorMode.AUTO)
      _uiState.update { it.copy(blinking = false) }
    }
  }

  private fun onPacket(state: TorState): String {
    val view = state.toView()
    lastSeq = state.seq
    // No countdown on the glasses: without it (seconds null) the alert views change only with the
    // text (and the TOR blink, which a packet does not reset), not every second over Bluetooth.
    wanted.update { current ->
      if (view.mode == TorMode.PRE_ALERT || view.mode == TorMode.TOR) {
        view.copy(seconds = null, dim = view.mode == TorMode.TOR && current.mode == TorMode.TOR && current.dim)
      } else {
        view
      }
    }
    _uiState.update {
      it.copy(lastState = state, lastPacketAt = SystemClock.elapsedRealtime(), packets = it.packets + 1)
    }
    followRecord(state.record)
    return answer(state.seq)
  }

  /** The PC asks for a recording while its packets carry "record" (the run's name). */
  private fun followRecord(name: String?) {
    val status = recorder.status.value
    // a failed recording is not tried again for the same run (every packet would), only for the next
    fun canStart(current: RecorderStatus) =
        current.state == "OFF" || (current.state == "ERROR" && current.name != name)
    when {
      name != null && canStart(status) ->
          viewModelScope.launch(Dispatchers.Main) {
            val session = glasses.startedSession
            if (!canStart(recorder.status.value)) return@launch
            if (session == null) {
              recorder.refuse(name, "Start the glasses display to record")
            } else {
              recorder.start(session, name)
            }
          }
      name == null && recorder.active -> viewModelScope.launch(Dispatchers.Main) { recorder.stop() }
    }
  }

  private fun answer(seq: Int): String =
      JSONObject()
          .put("seq", seq)
          .put("shown", shownSeq)
          .put("display", glasses.state.value.displayState?.name ?: "NONE")
          .put("rtr_request", rtrPresses.get())
          .put("recording", recorder.status.value.state)
          .toString()

  private suspend fun show(view: GlassesView) {
    sendLock.withLock {
      val start = SystemClock.elapsedRealtime()
      if (!glasses.send { torContent(view) }) return
      lastSentAt = SystemClock.elapsedRealtime()
      _uiState.update { it.copy(shownView = view, lastSendMs = lastSentAt - start) }
      Log.i(TAG, "Sent ${view.mode} ${view.seconds ?: ""} in ${lastSentAt - start} ms")
      if (view.seq >= 0 && view.seq != shownSeq) {
        shownSeq = view.seq
        receiver.reply(answer(view.seq)) // right away, so the PC can measure the latency
      }
    }
  }

  override fun onCleared() {
    recorder.stop()
    videoServer.stop()
    glasses.stop()
    receiver.stop()
    sounds.release()
    connectivity.unregisterNetworkCallback(networkCallback)
    wifiLock.release()
    super.onCleared()
  }
}

val UiState.displayReady: Boolean
  get() = glasses.displayState == DisplayState.STARTED
