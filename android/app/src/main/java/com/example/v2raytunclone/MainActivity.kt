package com.example.v2raytunclone

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLDecoder
import vpncore.Vpncore
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily

// Цвета RealityMaster
val RealityBgDark = Color(0xFF111315)
val RealityCardBg = Color(0xFF181A1E)
val RealityCyan = Color(0xFF42F5E3)
val RealityNeonGreen = Color(0xFF00FF7F)
val RealityCardBorder = Color(0xFF2B2E33)

// Модель сервера
data class VlessServer(
    val title: String,
    val host: String,
    val fullLink: String,
    var pingMs: Int = -1 // -1 значит еще не пинговали
)

class MainActivity : ComponentActivity() {

    private var pendingLink = ""

    private val vpnPermissionLauncher = registerForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            startMyVpn(pendingLink)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        LogManager.startLogging()
        setContent {
            RealityVpnApp(
                onConnectClick = { link, isCurrentlyConnected ->
                    if (isCurrentlyConnected) {
                        // Если уже подключено, мы кидаем интент на остановку
                        stopMyVpn()
                    } else {
                        pendingLink = link
                        val intent = android.net.VpnService.prepare(this@MainActivity)
                        if (intent != null) {
                            vpnPermissionLauncher.launch(intent)
                        } else {
                            startMyVpn(link)
                        }
                    }
                }
            )
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        LogManager.stopLogging()
        LogManager.clearLogs()
    }

    private fun startMyVpn(link: String) {
        val intent = Intent(this, MyVpnService::class.java).apply {
            action = "START_VPN"
            putExtra("VLESS_LINK", link)
        }
        startService(intent)
    }

    private fun stopMyVpn() {
        val intent = Intent(this, MyVpnService::class.java).apply {
            action = "STOP_VPN"
        }
        startService(intent)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RealityVpnApp(onConnectClick: (String, Boolean) -> Unit) {
    var showAddSubDialog by remember { mutableStateOf(false) }
    var showSettingsDialog by remember { mutableStateOf(false) }
    var showLogsDialog by remember { mutableStateOf(false) }

    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("vpn_prefs", android.content.Context.MODE_PRIVATE) }
    var subLinkInput by remember { mutableStateOf(prefs.getString("sub_link", "") ?: "") }
    var serversList by remember {
        mutableStateOf(deserializeServers(prefs.getString("servers_json", "") ?: ""))
    }
    var selectedServer by remember {
        val savedLink = prefs.getString("selected_server_link", "")
        val found = serversList.find { it.fullLink == savedLink }
        mutableStateOf(found ?: if (serversList.isNotEmpty()) serversList[0] else null)
    }
    var isConnected by remember { mutableStateOf(MyVpnService.isServiceRunning) }
    var isLoading by remember { mutableStateOf(false) }
    val coroutineScope = rememberCoroutineScope()

    // Синхронизация статуса сервиса
    LaunchedEffect(MyVpnService.isServiceRunning) {
        isConnected = MyVpnService.isServiceRunning
    }

    // Сохранение настроек в SharedPreferences
    LaunchedEffect(subLinkInput) {
        prefs.edit().putString("sub_link", subLinkInput).apply()
    }

    LaunchedEffect(serversList) {
        prefs.edit().putString("servers_json", serializeServers(serversList)).apply()
    }

    LaunchedEffect(selectedServer) {
        prefs.edit().putString("selected_server_link", selectedServer?.fullLink ?: "").apply()
    }

    // Применяем настройки DPI при запуске приложения
    LaunchedEffect(Unit) {
        val savedFrag = prefs.getBoolean("dpi_fragmentation", false)
        Vpncore.setDPISettings(savedFrag, false)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "Reality Master",
                        fontWeight = FontWeight.ExtraBold,
                        fontSize = 24.sp,
                        style = LocalTextStyle.current.copy(
                            brush = Brush.horizontalGradient(
                                colors = listOf(RealityCyan, RealityNeonGreen)
                            )
                        )
                    )
                },
                actions = {
                    IconButton(onClick = { showAddSubDialog = true }) {
                        Text("➕", fontSize = 20.sp)
                    }
                    IconButton(onClick = { showSettingsDialog = true }) {
                        Text("⚙️", fontSize = 20.sp)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = RealityBgDark,
                    titleContentColor = Color.White,
                    actionIconContentColor = Color.White
                )
            )
        }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(RealityBgDark)
                .padding(innerPadding)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                // Серверы
                if (serversList.isNotEmpty()) {
                    LazyColumn(
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        items(serversList) { server ->
                            ServerCard(
                                server = server,
                                isSelected = selectedServer?.fullLink == server.fullLink,
                                onClick = { selectedServer = server }
                            )
                        }
                    }
                } else {
                    Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("Список локаций пуст", color = Color.Gray, fontSize = 16.sp)
                            Spacer(modifier = Modifier.height(8.dp))
                            Text("Нажмите ➕ вверху для добавления подписки", color = Color.Gray.copy(alpha = 0.7f), fontSize = 13.sp)
                        }
                    }
                }

                // Кнопка подключения
                if (selectedServer != null) {
                    Button(
                        onClick = {
                            val wasConnected = isConnected
                            isConnected = !isConnected
                            onConnectClick(selectedServer!!.fullLink, wasConnected)
                        },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (isConnected) RealityCardBg else RealityNeonGreen
                        ),
                        shape = RoundedCornerShape(18.dp),
                        border = BorderStroke(1.dp, if (isConnected) Color(0xFFFF4C4C) else RealityNeonGreen),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 12.dp)
                            .height(65.dp)
                    ) {
                        Text(
                            text = if (isConnected) "ОТКЛЮЧИТЬ VPN" else "ПОДКЛЮЧИТЬ",
                            color = if (isConnected) Color(0xFFFF4C4C) else Color.Black,
                            fontSize = 20.sp,
                            fontWeight = FontWeight.ExtraBold
                        )
                    }
                }
            }

            // Индикатор загрузки
            if (isLoading) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(Color.Black.copy(alpha = 0.6f))
                        .clickable(enabled = false) {},
                    contentAlignment = Alignment.Center
                ) {
                    Surface(
                        color = RealityCardBg,
                        shape = RoundedCornerShape(16.dp),
                        border = BorderStroke(1.dp, RealityCardBorder),
                        modifier = Modifier.padding(32.dp)
                    ) {
                        Column(
                            modifier = Modifier.padding(24.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            CircularProgressIndicator(color = RealityCyan)
                            Spacer(modifier = Modifier.height(16.dp))
                            Text("Загрузка локаций...", color = Color.White, fontWeight = FontWeight.Medium)
                        }
                    }
                }
            }
        }
    }

    // Диалог добавления подписки
    if (showAddSubDialog) {
        AddSubscriptionDialog(
            initialLink = subLinkInput,
            onDismiss = { showAddSubDialog = false },
            onSave = { newLink ->
                showAddSubDialog = false
                subLinkInput = newLink
                if (newLink.isNotEmpty()) {
                    isLoading = true
                    coroutineScope.launch {
                        try {
                            val parsed = parseSubscriptionFromGo(newLink)
                            serversList = parsed
                            if (parsed.isNotEmpty()) {
                                selectedServer = parsed[0]
                            }
                            
                            // Фоновый пинг
                            launch {
                                for ((index, server) in parsed.withIndex()) {
                                    val ping = Vpncore.pingServer(server.fullLink)
                                    val updatedServer = server.copy(pingMs = ping.toInt())
                                    val newList = serversList.toMutableList()
                                    newList[index] = updatedServer
                                    serversList = newList
                                    if (selectedServer?.fullLink == server.fullLink) {
                                        selectedServer = updatedServer
                                    }
                                }
                            }
                        } catch (e: Exception) {
                            Log.e("VPN_UI", "Ошибка: ${e.message}")
                            withContext(Dispatchers.Main) {
                                Toast.makeText(context, "Ошибка загрузки: ${e.localizedMessage}", Toast.LENGTH_LONG).show()
                            }
                        } finally {
                            isLoading = false
                        }
                    }
                }
            }
        )
    }

    // Диалог настроек
    if (showSettingsDialog) {
        SettingsDialog(
            onDismiss = { showSettingsDialog = false },
            onShowLogs = {
                showSettingsDialog = false
                showLogsDialog = true
            }
        )
    }

    // Диалог логов
    if (showLogsDialog) {
        LogsDialog(
            onDismiss = { showLogsDialog = false }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddSubscriptionDialog(
    initialLink: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit
) {
    var text by remember { mutableStateOf(initialLink) }
    val clipboardManager = LocalClipboardManager.current

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = RealityCardBg,
        shape = RoundedCornerShape(20.dp),
        modifier = Modifier.padding(16.dp),
        title = {
            Text(
                text = "Добавить подписку",
                color = Color.White,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold
            )
        },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    placeholder = { Text("Вставьте ссылку на подписку", color = Color.Gray) },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = RealityCyan,
                        unfocusedBorderColor = RealityCardBorder,
                        focusedTextColor = Color.White,
                        unfocusedTextColor = Color.White,
                        cursorColor = RealityCyan
                    ),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(modifier = Modifier.height(12.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End
                ) {
                    TextButton(
                        onClick = {
                            val clipText = clipboardManager.getText()?.text ?: ""
                            if (clipText.isNotEmpty()) {
                                text = clipText
                            }
                        },
                        colors = ButtonDefaults.textButtonColors(contentColor = RealityCyan)
                    ) {
                        Text("📋 Вставить")
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onSave(text) },
                colors = ButtonDefaults.buttonColors(containerColor = RealityCyan),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Загрузить", color = Color.Black, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                colors = ButtonDefaults.textButtonColors(contentColor = Color.Gray)
            ) {
                Text("Отмена")
            }
        }
    )
}

@Composable
fun SettingsDialog(
    onDismiss: () -> Unit,
    onShowLogs: () -> Unit
) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("vpn_prefs", android.content.Context.MODE_PRIVATE) }
    var fragmentation by remember { mutableStateOf(prefs.getBoolean("dpi_fragmentation", false)) }

    LaunchedEffect(fragmentation) {
        prefs.edit().putBoolean("dpi_fragmentation", fragmentation).apply()
        Vpncore.setDPISettings(fragmentation, false)
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = RealityCardBg,
        shape = RoundedCornerShape(20.dp),
        modifier = Modifier.padding(16.dp),
        title = {
            Text(
                text = "Настройки",
                color = Color.White,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold
            )
        },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                Surface(
                    color = RealityBgDark,
                    shape = RoundedCornerShape(12.dp),
                    border = BorderStroke(1.dp, RealityCardBorder),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("TCP Фрагментация", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Medium)
                            Text("Разбивает ClientHello пакеты", color = Color.Gray, fontSize = 12.sp)
                        }
                        Switch(
                            checked = fragmentation,
                            onCheckedChange = { fragmentation = it },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = RealityNeonGreen,
                                checkedTrackColor = Color(0xFF1E2125),
                                uncheckedThumbColor = Color.Gray,
                                uncheckedTrackColor = RealityBgDark
                            )
                        )
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = onShowLogs,
                    colors = ButtonDefaults.buttonColors(containerColor = RealityBgDark),
                    shape = RoundedCornerShape(12.dp),
                    border = BorderStroke(1.dp, RealityCardBorder),
                    modifier = Modifier.fillMaxWidth().height(50.dp)
                ) {
                    Text("📜 Логи подключения", color = RealityCyan, fontWeight = FontWeight.Bold)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = onDismiss,
                colors = ButtonDefaults.buttonColors(containerColor = RealityCyan),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Готово", color = Color.Black, fontWeight = FontWeight.Bold)
            }
        }
    )
}

@Composable
fun LogsDialog(
    onDismiss: () -> Unit
) {
    val logs = LogManager.logs
    val listState = rememberLazyListState()
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current

    LaunchedEffect(logs.size) {
        if (logs.isNotEmpty()) {
            listState.animateScrollToItem(logs.size - 1)
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = RealityCardBg,
        shape = RoundedCornerShape(20.dp),
        modifier = Modifier
            .padding(16.dp)
            .fillMaxWidth()
            .fillMaxHeight(0.8f),
        title = {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Логи подключения",
                    color = Color.White,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold
                )
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    IconButton(onClick = {
                        val fullLogText = logs.joinToString("\n") { it.original }
                        clipboardManager.setText(AnnotatedString(fullLogText))
                        Toast.makeText(context, "Логи скопированы!", Toast.LENGTH_SHORT).show()
                    }) {
                        Text("📋", fontSize = 16.sp)
                    }
                    IconButton(onClick = {
                        LogManager.clearLogs()
                    }) {
                        Text("🗑️", fontSize = 16.sp)
                    }
                }
            }
        },
        text = {
            Surface(
                color = RealityBgDark,
                shape = RoundedCornerShape(12.dp),
                border = BorderStroke(1.dp, RealityCardBorder),
                modifier = Modifier.fillMaxSize()
            ) {
                if (logs.isEmpty()) {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(
                            text = "Логи пусты. Запустите VPN для просмотра логов.",
                            color = Color.Gray,
                            fontSize = 14.sp
                        )
                    }
                } else {
                    LazyColumn(
                        state = listState,
                        modifier = Modifier.fillMaxSize().padding(8.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        items(logs) { logLine ->
                            LogItemView(logLine)
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = onDismiss,
                colors = ButtonDefaults.buttonColors(containerColor = RealityCyan),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("Закрыть", color = Color.Black, fontWeight = FontWeight.Bold)
            }
        }
    )
}

fun getProtocolLabelAndColor(link: String): Pair<String, Color> {
    return when {
        link.startsWith("vless://", ignoreCase = true) -> Pair("VLESS Reality", RealityCyan)
        link.startsWith("naive://", ignoreCase = true) || link.startsWith("naive+https://", ignoreCase = true) -> Pair("NaiveProxy", Color(0xFFB388FF))
        link.startsWith("olcrtc://", ignoreCase = true) -> Pair("WebRTC (OlcRTC)", RealityNeonGreen)
        else -> Pair("Unknown", Color.Gray)
    }
}

@Composable
fun ServerCard(server: VlessServer, isSelected: Boolean, onClick: () -> Unit) {
    val borderColor = if (isSelected) RealityCyan else RealityCardBorder
    val backgroundColor = if (isSelected) Color(0xFF1E2125) else RealityCardBg
    val (protoLabel, protoColor) = getProtocolLabelAndColor(server.fullLink)

    Surface(
        shape = RoundedCornerShape(16.dp),
        color = backgroundColor,
        border = BorderStroke(1.dp, borderColor),
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() }
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(text = getCountryEmoji(server.title), fontSize = 28.sp)
            Spacer(modifier = Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(text = server.title, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Medium)
                Spacer(modifier = Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Surface(
                        color = protoColor.copy(alpha = 0.15f),
                        border = BorderStroke(1.dp, protoColor.copy(alpha = 0.5f)),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.padding(end = 8.dp)
                    ) {
                        Text(
                            text = protoLabel,
                            color = protoColor,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                        )
                    }
                    Text(text = server.host, color = Color.Gray, fontSize = 12.sp)
                }
            }
            
            // Вывод Пинга
            if (server.pingMs == -1) {
                CircularProgressIndicator(color = RealityCyan, modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            } else if (server.pingMs == 0 || server.pingMs > 2000) {
                Text("Error", color = Color(0xFFFF4C4C), fontSize = 14.sp, fontWeight = FontWeight.Bold)
            } else {
                val pingColor = if (server.pingMs < 100) RealityNeonGreen else if (server.pingMs < 300) Color(0xFFFFC107) else Color(0xFFFF4C4C)
                Text("${server.pingMs} ms", color = pingColor, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
fun LogItemView(logLine: LogLine) {
    val levelColor = when (logLine.level) {
        "E", "F" -> Color(0xFFFF4C4C)
        "W" -> Color(0xFFFFC107)
        "I" -> Color(0xFF00FF7F)
        "D" -> Color(0xFF90A4AE)
        else -> Color.White
    }

    val tagColor = when (logLine.tag) {
        "GoLog" -> RealityCyan
        "VPN", "VPN_CORE", "VPN_UI" -> RealityNeonGreen
        else -> Color(0xFF81D4FA)
    }

    Column(modifier = Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.Top) {
            if (logLine.time.isNotEmpty()) {
                Text(
                    text = logLine.time.substringAfter(" "), // Показываем только время без даты
                    color = Color.Gray,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.padding(end = 6.dp)
                )
            }
            Text(
                text = "${logLine.level}/${logLine.tag}:",
                color = tagColor,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(end = 6.dp)
            )
            Text(
                text = logLine.message,
                color = levelColor,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
        }
    }
}

// ---------------------- ОПРЕДЕЛИТЕЛЬ ФЛАГОВ ----------------------------
fun getCountryEmoji(title: String): String {
    val lower = title.lowercase()
    if (lower.contains("герман") || lower.contains("germany") || lower.contains("de") || lower.contains("берлин")) return "🇩🇪"
    if (lower.contains("нидерланд") || lower.contains("netherland") || lower.contains("nl")) return "🇳🇱"
    if (lower.contains("турц") || lower.contains("turkey") || lower.contains("tr") || lower.contains("стамбул")) return "🇹🇷"
    if (lower.contains("британ") || lower.contains("uk") || lower.contains("london")) return "🇬🇧"
    if (lower.contains("росси") || lower.contains("russia") || lower.contains("ru") || lower.contains("москва")) return "🇷🇺"
    if (lower.contains("гонконг") || lower.contains("hongkong") || lower.contains("hk")) return "🇭🇰"
    if (lower.contains("америк") || lower.contains("сша") || lower.contains("us") || lower.contains("нью-йорк")) return "🇺🇸"
    if (lower.contains("финлянд") || lower.contains("finland") || lower.contains("fi")) return "🇫🇮"
    if (lower.contains("франц") || lower.contains("france") || lower.contains("fr") || lower.contains("париж")) return "🇫🇷"
    if (lower.contains("польш") || lower.contains("poland") || lower.contains("pl")) return "🇵🇱"
    if (lower.contains("швец") || lower.contains("sweden") || lower.contains("se")) return "🇸🇪"
    return "🌍"
}

// ---------------------- ПАРСЕР ПОДПИСКИ С GO-ЯДРА ----------------------------
suspend fun parseSubscriptionFromGo(subUrl: String): List<VlessServer> = withContext(Dispatchers.IO) {
    val servers = mutableListOf<VlessServer>()
    try {
        val jsonString = Vpncore.fetchSubscription(subUrl)
        val jsonArray = JSONArray(jsonString)
        for (i in 0 until jsonArray.length()) {
            val obj = jsonArray.getJSONObject(i)
            val host = obj.optString("Host", "Unknown")
            
            // Если Title пустой в JSON - Го-ядро могло вернуть пустую строку, обрабатываем!
            var title = URLDecoder.decode(obj.optString("Title", ""), "UTF-8")
            if (title.isEmpty()) {
                val sni = obj.optString("SNI", "")
                title = if (sni.isNotEmpty()) "VLESS ($sni)" else "Сервер $host"
            }
            
            var fullLink = obj.optString("FullLink", "")
            // Резервный фолбек, если FullLink не вернулся
            if (fullLink.isEmpty()) {
                val port = obj.getString("Port")
                val uuid = obj.getString("UUID")
                val sni = obj.optString("SNI", "")
                val pbk = obj.optString("PublicKey", "")
                val sid = obj.optString("ShortId", "")
                val flow = obj.optString("Flow", "")
                fullLink = "vless://$uuid@$host:$port?type=tcp&security=reality&sni=$sni&pbk=$pbk&sid=$sid&flow=$flow"
            }

            servers.add(VlessServer(title, host, fullLink))
        }
    } catch (e: Exception) {
        Log.e("VPN_CORE", "Ошибка: ${e.message}")
    }
    return@withContext servers
}

// ---------------------- СЕРИАЛИЗАЦИЯ ДЛЯ PERSISTENCE ----------------------------
fun serializeServers(servers: List<VlessServer>): String {
    val array = JSONArray()
    for (s in servers) {
        val obj = JSONObject()
        obj.put("title", s.title)
        obj.put("host", s.host)
        obj.put("fullLink", s.fullLink)
        obj.put("pingMs", s.pingMs)
        array.put(obj)
    }
    return array.toString()
}

fun deserializeServers(jsonStr: String): List<VlessServer> {
    val list = mutableListOf<VlessServer>()
    if (jsonStr.isNullOrEmpty()) return list
    try {
        val array = JSONArray(jsonStr)
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            list.add(
                VlessServer(
                    title = obj.optString("title", ""),
                    host = obj.optString("host", ""),
                    fullLink = obj.optString("fullLink", ""),
                    pingMs = obj.optInt("pingMs", -1)
                )
            )
        }
    } catch (e: Exception) {
        Log.e("VPN_UI", "Ошибка десериализации серверов: ${e.message}")
    }
    return list
}
