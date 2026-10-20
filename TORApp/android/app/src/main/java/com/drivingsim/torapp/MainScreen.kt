package com.drivingsim.torapp

import android.os.SystemClock
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.meta.wearable.dat.core.types.RegistrationState
import kotlinx.coroutines.delay

private val ERROR_COLOR = Color(0xFFB3261E)

@Composable
fun MainScreen(
    viewModel: TorViewModel,
    onRegister: () -> Unit,
    onUnregister: () -> Unit,
    onFirmwareUpdate: () -> Unit,
    onDatAppUpdate: () -> Unit,
) {
  val state by viewModel.uiState.collectAsStateWithLifecycle()
  // re-read the clock twice a second for "receiving" and the packet age
  var now by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
  LaunchedEffect(Unit) {
    while (true) {
      delay(500)
      now = SystemClock.elapsedRealtime()
    }
  }

  Column(
      modifier =
          Modifier.fillMaxSize()
              .safeDrawingPadding()
              .verticalScroll(rememberScrollState())
              .padding(16.dp),
      verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    Text("TORApp", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
    Text(
        "Takeover requests from the CARLA simulator on the Meta Ray-Ban Display glasses",
        style = MaterialTheme.typography.bodyMedium,
    )

    Section("1. Meta AI app") {
      val registered = state.registrationState == RegistrationState.REGISTERED
      Line("Registration", state.registrationState.name)
      state.registrationError?.let { ErrorText(it) }
      if (registered) {
        OutlinedButton(onClick = onUnregister) { Text("Disconnect from Meta AI") }
      } else {
        Button(onClick = onRegister) { Text("Connect to Meta AI") }
      }
    }

    Section("2. Glasses display") {
      Line("Glasses", if (state.glassesConnected) "connected" else "not connected")
      Line("Session", state.glasses.sessionState?.name ?: "-")
      Line("Display", state.glasses.displayState?.name ?: "-")
      state.glasses.error?.let { ErrorText(it) }
      if (state.firmwareUpdateRequired) {
        OutlinedButton(onClick = onFirmwareUpdate) { Text("Update glasses firmware") }
      }
      if (state.glasses.datAppUpdateRequired) {
        OutlinedButton(onClick = onDatAppUpdate) { Text("Update app on the glasses") }
      }
      if (state.glasses.active) {
        OutlinedButton(onClick = viewModel::stopGlasses) { Text("Stop display") }
      } else {
        Button(
            onClick = viewModel::startGlasses,
            enabled = state.registrationState == RegistrationState.REGISTERED,
        ) {
          Text("Start display")
        }
      }
      Row(verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
          Text("Keep display awake")
          Text(
              "Resend the view every 15 s (the display dims after 20 s)",
              style = MaterialTheme.typography.bodySmall,
          )
        }
        Switch(checked = state.keepAwake, onCheckedChange = viewModel::setKeepAwake)
      }
    }

    Section("3. Simulator PC") {
      Line("This phone", state.phoneAddress?.let { "$it : $TOR_PORT (UDP)" } ?: "no network")
      state.receiveError?.let { ErrorText(it) }
      val age = if (state.lastPacketAt == 0L) null else (now - state.lastPacketAt) / 1000.0
      Line(
          "PC",
          when {
            age == null -> "nothing received yet"
            age < 2.0 -> "receiving (${state.packets} packets)"
            else -> "last packet %.0f s ago".format(age)
          },
      )
      state.lastState?.let { last ->
        Line("State", last.mode.name + (last.remaining?.let { " %.1f s".format(it) } ?: ""))
      }
      Line("On the glasses", state.shownView?.let { describe(it) } ?: "-")
      Line("Last send", state.lastSendMs?.let { "$it ms" } ?: "-")
      Text(
          "On the PC: python PythonAPI\\examples\\takeover_experiment.py --glasses " +
              (state.phoneAddress ?: "PHONE_IP"),
          style = MaterialTheme.typography.bodySmall,
      )
    }

    Section("Test (without the PC)") {
      Text(
          "Shows a mode on the glasses. While the PC sends, its state replaces it.",
          style = MaterialTheme.typography.bodySmall,
      )
      Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { viewModel.test(TorMode.AUTO) }, enabled = state.displayReady) {
          Text("AUTO")
        }
        OutlinedButton(
            onClick = { viewModel.test(TorMode.PRE_ALERT) },
            enabled = state.displayReady,
        ) {
          Text("PRE")
        }
        OutlinedButton(onClick = { viewModel.test(TorMode.TOR) }, enabled = state.displayReady) {
          Text("TOR")
        }
        OutlinedButton(onClick = { viewModel.test(TorMode.MANUAL) }, enabled = state.displayReady) {
          Text("MAN")
        }
      }
      Text(
          "Display area: 600x600 frame and grid. Text: native text lines (swipe to scroll).",
          style = MaterialTheme.typography.bodySmall,
      )
      Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(
            onClick = { viewModel.testDisplay(DisplayTest.AREA) },
            enabled = state.displayReady,
        ) {
          Text("AREA")
        }
        OutlinedButton(
            onClick = { viewModel.testDisplay(DisplayTest.TEXT) },
            enabled = state.displayReady,
        ) {
          Text("TEXT")
        }
      }
      Text(
          "Blink: TOR banner flashing for 6 s. Compare with \"Last send\": a period shorter " +
              "than the send time skips flashes.",
          style = MaterialTheme.typography.bodySmall,
      )
      Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for (period in listOf(250L, 500L, 1000L)) {
          OutlinedButton(
              onClick = { viewModel.testBlink(period) },
              enabled = state.displayReady && !state.blinking,
          ) {
            Text("$period ms")
          }
        }
      }
    }
    Spacer(Modifier.padding(8.dp))
  }
}

private fun describe(view: GlassesView): String =
    view.mode.name +
        (if (view.message.isNotEmpty()) " - ${view.message}" else "") +
        (view.seconds?.let { " ($it s)" } ?: "")

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
  Card(modifier = Modifier.fillMaxWidth()) {
    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
      Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
      content()
    }
  }
}

@Composable
private fun Line(label: String, value: String) {
  Row(modifier = Modifier.fillMaxWidth()) {
    Text(label, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
    Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
  }
}

@Composable
private fun ErrorText(message: String) {
  Text(message, color = ERROR_COLOR, style = MaterialTheme.typography.bodySmall)
}
