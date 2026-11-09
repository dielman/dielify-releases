package com.dielify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.dielify.app.net.ApiError
import com.dielify.app.net.PairInfo
import com.dielify.app.net.pairCode
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import kotlinx.coroutines.launch

// 0.9.10: sign a TV in. The TV shows a QR code; scan it here (Google's scanner: no camera
// permission for Dielify), check it's your TV, pick whose music it plays and allow it.
// Parents only: a kids account is told to ask a parent (pair_api.py).

@Composable
fun PairTvScreen(vm: AppViewModel, startCode: String?) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf(startCode?.let(::pairCode)) }
    var info by remember { mutableStateOf<PairInfo?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var person by remember { mutableStateOf<String?>(null) }
    var typed by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    fun scan() {
        error = null
        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
        GmsBarcodeScanning.getClient(context, options).startScan()
            .addOnSuccessListener { b -> b.rawValue?.let { code = pairCode(it) } }
            .addOnFailureListener { error = "The scanner didn't start (${it.message}). Type the code instead." }
    }

    LaunchedEffect(code) {
        val c = code ?: return@LaunchedEffect
        info = null; error = null
        try {
            val i = vm.server.pairInfo(c)
            info = i
            person = i.people.firstOrNull { it.name.equals(i.suggested, true) && it.canSignIn }?.name
                ?: i.people.firstOrNull { it.canSignIn }?.name
        } catch (e: ApiError) {
            error = e.message
        } catch (e: Exception) {
            error = "Couldn't reach your PC: ${e.message}"
        }
    }

    Page(vm, "Sign in a TV") { pad ->
        Column(Modifier.padding(pad).padding(20.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            val i = info
            if (i == null) {
                Text("Open Dielify on the TV. It shows a QR code: scan it here.")
                Button(onClick = { scan() }) {
                    Icon(Icons.Filled.QrCodeScanner, null, Modifier.padding(end = 8.dp)); Text("Scan the TV's code")
                }
                OutlinedTextField(typed, { typed = it }, label = { Text("Or type the code (e.g. KDW7-RT3P)") },
                    singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedButton(onClick = { code = pairCode(typed) }, enabled = typed.isNotBlank()) { Text("Look it up") }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                return@Column
            }
            Text(i.deviceName, style = MaterialTheme.typography.headlineSmall)
            Text("At ${i.address} · code ${i.code}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Only allow a TV you can see showing this code.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Whose music it plays", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
            i.people.forEach { p ->
                Row(Modifier.fillMaxWidth().selectable(p.name == person, enabled = p.canSignIn, role = Role.RadioButton) { person = p.name },
                    verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = p.name == person, onClick = null, enabled = p.canSignIn)
                    Column(Modifier.padding(start = 8.dp)) {
                        Text(p.name)
                        val note = listOfNotNull(if (p.role == "child") "kids account: her controls apply" else null,
                            if (!p.canSignIn) "no phone login yet (add one on the PC)" else null)
                        if (note.isNotEmpty()) Text(note.joinToString(" · "), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(enabled = person != null && !busy, onClick = {
                    busy = true
                    scope.launch {
                        try {
                            val r = vm.server.pairApprove(i.code, person!!)
                            vm.messages.tryEmit("${r.deviceName} is signed in for ${r.person}")
                            vm.back()
                        } catch (e: ApiError) {
                            error = e.message
                        } catch (e: Exception) {
                            error = "Couldn't reach your PC: ${e.message}"
                        }
                        busy = false
                    }
                }) { Text("Allow") }
                TextButton(onClick = {
                    scope.launch { runCatching { vm.server.pairRefuse(i.code) }; vm.back() }
                }) { Text("Don't allow") }
            }
        }
    }
}
