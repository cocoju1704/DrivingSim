package com.drivingsim.torapp

import android.Manifest.permission.BLUETOOTH
import android.Manifest.permission.BLUETOOTH_CONNECT
import android.Manifest.permission.INTERNET
import android.os.Bundle
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.Permission

class MainActivity : ComponentActivity() {
  companion object {
    private val PERMISSIONS = arrayOf(BLUETOOTH, BLUETOOTH_CONNECT, INTERNET)
  }

  private val viewModel: TorViewModel by viewModels()
  // the glasses' camera and microphone for the recording, asked one after the other (Meta AI app)
  private val glassesPermissions = ArrayDeque<Permission>()
  private val glassesPermissionLauncher =
      registerForActivityResult(Wearables.RequestPermissionContract()) {
        viewModel.checkGlassesPermissions()
        glassesPermissions.removeFirstOrNull()?.let { next -> launchGlassesPermission(next) }
      }

  private fun requestGlassesPermissions() {
    glassesPermissions.clear()
    glassesPermissions.addAll(listOf(Permission.CAMERA, Permission.MICROPHONE))
    launchGlassesPermission(glassesPermissions.removeFirst())
  }

  private fun launchGlassesPermission(permission: Permission) {
    glassesPermissionLauncher.launch(permission)
  }
  private val permissionsLauncher =
      registerForActivityResult(RequestMultiplePermissions()) { results ->
        if (results.entries.all { it.value }) {
          viewModel.startObserving()
        } else {
          Toast.makeText(this, "Bluetooth permission is required", Toast.LENGTH_SHORT).show()
        }
      }

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    enableEdgeToEdge()
    // The phone stays on during the experiment: Android delays UDP and Bluetooth for a sleeping app.
    window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    setContent {
      MaterialTheme {
        MainScreen(
            viewModel = viewModel,
            onRegister = { viewModel.register(this) },
            onUnregister = { viewModel.unregister(this) },
            onFirmwareUpdate = { viewModel.openFirmwareUpdate(this) },
            onDatAppUpdate = { viewModel.openDatAppUpdate(this) },
            onGlassesPermissions = ::requestGlassesPermissions,
        )
      }
    }
  }

  override fun onStart() {
    super.onStart()
    permissionsLauncher.launch(PERMISSIONS)
  }
}
