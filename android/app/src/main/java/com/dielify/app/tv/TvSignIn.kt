package com.dielify.app.tv

import android.graphics.Bitmap
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.ApiError
import com.dielify.app.net.PairStart
import com.dielify.app.ui.AppViewModel
import com.dielify.app.ui.Bg
import com.dielify.app.ui.tintBrush
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import kotlinx.coroutines.delay

// 0.9.10: the TV signs in without typing anything: it finds the PC on the home network, shows a
// QR code, and a parent allows it from the Dielify phone app (or types the code on the PC).

@Composable
fun TvSignIn(vm: AppViewModel) {
    val context = LocalContext.current
    val pcs by remember { findPcs(context) }.collectAsStateWithLifecycle(emptyList())
    var chosen by remember { mutableStateOf<String?>(null) }
    var typing by remember { mutableStateOf(false) }
    var typed by remember { mutableStateOf(vm.lastAddresses.firstOrNull() ?: "") }
    var lookedLong by remember { mutableStateOf(false) }
    var pair by remember { mutableStateOf<PairStart?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableIntStateOf(0) }
    val deviceName = remember {
        Settings.Global.getString(context.contentResolver, Settings.Global.DEVICE_NAME)?.takeIf { it.isNotBlank() }
            ?: "${Build.MANUFACTURER} ${Build.MODEL}"
    }

    LaunchedEffect(lookedLong) { if (!lookedLong) { delay(8_000); lookedLong = true } }  // "Look again" looks for 8 s more
    LaunchedEffect(pcs) { if (chosen == null && pcs.size == 1) chosen = pcs.first().address }

    LaunchedEffect(chosen, attempt) {
        val address = chosen ?: return@LaunchedEffect
        pair = null
        try {
            val p = vm.server.pairStart(address, deviceName)
            pair = p
            message = null
            while (true) {
                delay(2_000)
                val s = vm.server.pairPoll(address, p.secret)
                when (s.status) {
                    "approved" -> { vm.server.account?.let(vm::signedIn); return@LaunchedEffect }
                    "refused" -> { message = "That wasn't allowed. Here's a new code."; attempt++; return@LaunchedEffect }
                    "expired" -> { attempt++; return@LaunchedEffect }  // a new code
                }
            }
        } catch (e: ApiError) {
            message = e.message
        }
    }

    Box(Modifier.fillMaxSize().background(tintBrush(null, 1200f)).background(Bg.copy(alpha = 0.4f)).padding(horizontal = TvPadH * 1.5f, vertical = TvPadV * 1.5f)) {
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(40.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Dielify", style = MaterialTheme.typography.displaySmall)
                val p = pair
                when {
                    typing || (chosen == null && lookedLong && pcs.isEmpty()) -> {
                        val connect = remember { FocusRequester() }
                        Text(if (typing) "Type the PC's address" else "Couldn't find Dielify on this network.",
                            style = MaterialTheme.typography.headlineSmall)
                        Text("Dielify on the PC shows it under Settings > People & phones (e.g. 192.168.1.249:4747).",
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        OutlinedTextField(typed, { typed = it }, singleLine = true, label = { Text("PC address") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                            keyboardActions = KeyboardActions(onGo = { typing = false; chosen = typed.trim(); attempt++ }),
                            modifier = Modifier.width(360.dp).focusProperties { down = connect }.leaveWithArrows())
                        TvActions {
                            TvButton("Connect", modifier = Modifier.focusRequester(connect), primary = true) { typing = false; chosen = typed.trim(); attempt++ }
                            if (!typing) TvButton("Look again", Icons.Filled.Refresh) { lookedLong = false; attempt++ }
                        }
                    }
                    chosen == null && pcs.size > 1 -> {
                        Text("Which PC?", style = MaterialTheme.typography.headlineSmall)
                        val first = remember { FocusRequester() }
                        pcs.forEachIndexed { i, pc ->
                            TvButton("${pc.name}  ·  ${pc.address}", modifier = if (i == 0) Modifier.focusRequester(first) else Modifier) {
                                chosen = pc.address
                            }
                        }
                        LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
                    }
                    p == null -> Text(message ?: if (chosen == null) "Looking for Dielify on your network…" else "Connecting to your PC…",
                        style = MaterialTheme.typography.headlineSmall)
                    else -> {
                        Text("Sign this TV in", style = MaterialTheme.typography.headlineSmall)
                        Text("On your phone: Dielify > Settings > Sign in a TV, then scan the code. " +
                            "Or on the PC: Settings > People & phones > Add a TV.",
                            style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(p.code, fontSize = 40.sp, lineHeight = 48.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 4.sp, maxLines = 1, softWrap = false)
                        message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                        Text("Connected to ${chosen ?: ""}. A parent chooses whose music this TV plays.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                if (!typing && pair != null || (message != null && pair == null && chosen != null)) {
                    TvActions {
                        TvButton("Type the PC's address instead") { typing = true }
                        if (pair == null) TvButton("Try again", Icons.Filled.Refresh) { attempt++ }
                    }
                }
            }
            pair?.let { p ->
                val qr = remember(p.link) { qrBitmap(p.link) }
                Box(Modifier.size(270.dp).clip(RoundedCornerShape(16.dp)).background(Color.White).padding(14.dp)) {
                    Image(qr, "QR code for ${p.code}", Modifier.fillMaxSize())
                }
            }
        }
    }
}

/** A QR code as an image (black on white). */
fun qrBitmap(text: String, size: Int = 600): ImageBitmap {
    val m = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 1))
    val px = IntArray(size * size) { i -> if (m[i % size, i / size]) android.graphics.Color.BLACK else android.graphics.Color.WHITE }
    return Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888).apply { setPixels(px, 0, size, 0, 0, size, size) }.asImageBitmap()
}
