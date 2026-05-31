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
    var currentRoute by remember { mutableStateOf("home") }

    Scaffold(
        bottomBar = {
            NavigationBar(
                containerColor = RealityBgDark,
                contentColor = Color.White
            ) {
                NavigationBarItem(
                    selected = currentRoute == "home",
                    onClick = { currentRoute = "home" },
                    icon = { Text("🌍") },
                    label = { Text("Серверы", color = Color.LightGray) },
                    colors = NavigationBarItemDefaults.colors(indicatorColor = RealityCardBg)
                )
                NavigationBarItem(
                    selected = currentRoute == "settings",
                    onClick = { currentRoute = "settings" },
                    icon = { Text("⚡") },
                    label = { Text("DPI обход", color = Color.LightGray) },
                    colors = NavigationBarItemDefaults.colors(indicatorColor = RealityCardBg)
                )
                NavigationBarItem(
                    selected = currentRoute == "logs",
                    onClick = { currentRoute = "logs" },
                    icon = { Text("📜") },
                    label = { Text("Логи", color = Color.LightGray) },
                    colors = NavigationBarItemDefaults.colors(indicatorColor = RealityCardBg)
                )
            }
        }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(RealityBgDark)
                .padding(innerPadding)
        ) {
            when (currentRoute) {
                "home" -> HappVpnScreen(onConnectClick)
                "settings" -> DPISettingsScreen()
                "logs" -> LogsScreen()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HappVpnScreen(onConnectClick: (String, Boolean) -> Unit) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("vpn_prefs", android.content.Context.MODE_PRIVATE) }

    var subLinkInput by remember { mutableStateOf(prefs.getString("sub_link", "") ?: "") }
    var serversList by remember {
        mutableStateOf(deserializeServers(prefs.getString("servers_json", "") ?: ""))
    }
    var isLoading by remember { mutableStateOf(false) }
    var selectedServer by remember {
        val savedLink = prefs.getString("selected_server_link", "")
        val found = serversList.find { it.fullLink == savedLink }
        mutableStateOf(found ?: if (serversList.isNotEmpty()) serversList[0] else null)
    }
    var isConnected by remember { mutableStateOf(MyVpnService.isServiceRunning) }
    val coroutineScope = rememberCoroutineScope()

    LaunchedEffect(MyVpnService.isServiceRunning) {
        isConnected = MyVpnService.isServiceRunning
    }

    LaunchedEffect(subLinkInput) {
        prefs.edit().putString("sub_link", subLinkInput).apply()
    }

    LaunchedEffect(serversList) {
        prefs.edit().putString("servers_json", serializeServers(serversList)).apply()
    }

    LaunchedEffect(selectedServer) {
        prefs.edit().putString("selected_server_link", selectedServer?.fullLink ?: "").apply()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "Reality Master",
            color = RealityCyan,
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 10.dp, bottom = 20.dp)
        )

        OutlinedTextField(
            value = subLinkInput,
            onValueChange = { subLinkInput = it },
            label = { Text("Ссылка-подписка", color = Color.Gray) },
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = RealityCyan,
                unfocusedBorderColor = RealityCardBorder,
                focusedTextColor = Color.White,
                unfocusedTextColor = Color.White
            ),
            modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
            shape = RoundedCornerShape(12.dp)
        )

        Button(
            onClick = {
                if (subLinkInput.isNotEmpty()) {
                    isLoading = true
                    coroutineScope.launch {
                        try {
                            val parsed = parseSubscriptionFromGo(subLinkInput)
                            serversList = parsed
                            if (parsed.isNotEmpty()) selectedServer = parsed[0]
                            
                            // Запускаем фоновый пинг серверов
                            launch {
                                for ((index, server) in parsed.withIndex()) {
                                    val ping = Vpncore.pingServer(server.fullLink)
                                    val updatedServer = server.copy(pingMs = ping.toInt())
                                    // Обновляем элемент в списке "на лету"
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
                        } finally {
                            isLoading = false
                        }
                    }
                }
            },
            colors = ButtonDefaults.buttonColors(containerColor = RealityCardBg),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().height(55.dp),
            border = BorderStroke(1.dp, RealityCardBorder)
        ) {
            if (isLoading) {
                CircularProgressIndicator(color = RealityCyan, modifier = Modifier.size(24.dp))
            } else {
                Text("🔄 Обновить локации", color = RealityCyan, fontSize = 16.sp)
            }
        }

        Spacer(modifier = Modifier.height(20.dp))

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
                Text("Список серверов пуст", color = Color.Gray)
            }
        }

        if (selectedServer != null) {
            Button(
                onClick = {
                    val wasConnected = isConnected
                    isConnected = !isConnected // Переключаем стейт интерфейса
                    onConnectClick(selectedServer!!.fullLink, wasConnected)
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (isConnected) RealityCardBg else RealityNeonGreen
                ),
                shape = RoundedCornerShape(18.dp),
                border = BorderStroke(1.dp, if (isConnected) Color(0xFFFF4C4C) else RealityNeonGreen),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 10.dp)
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
}

@Composable
fun ServerCard(server: VlessServer, isSelected: Boolean, onClick: () -> Unit) {
    val borderColor = if (isSelected) RealityCyan else RealityCardBorder
    val backgroundColor = if (isSelected) Color(0xFF1E2125) else RealityCardBg

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
                Text(text = server.host, color = Color.Gray, fontSize = 12.sp)
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
fun DPISettingsScreen() {
    var fakeRST by remember { mutableStateOf(false) }
    var fragmentation by remember { mutableStateOf(false) }

    // Как только юзер дергает ползунки, отправляем это в Go ядро
    LaunchedEffect(fakeRST, fragmentation) {
        Vpncore.setDPISettings(fragmentation, fakeRST)
    }

    Column(modifier = Modifier.padding(16.dp).fillMaxSize()) {
        Text("DPI Обход (Фрагментация)", color = RealityCyan, fontSize = 24.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(bottom = 20.dp, top = 20.dp))
        
        Surface(color = RealityCardBg, shape = RoundedCornerShape(12.dp), border = BorderStroke(1.dp, RealityCardBorder), modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp)) {
            Row(modifier = Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("TCP Фрагментация", color = Color.White, fontSize = 18.sp)
                    Text("Разбивает ClientHello пакеты", color = Color.Gray, fontSize = 12.sp)
                }
                Switch(checked = fragmentation, onCheckedChange = { fragmentation = it }, colors = SwitchDefaults.colors(checkedThumbColor = RealityNeonGreen, checkedTrackColor = Color(0xFF1E2125)))
            }
        }

        Surface(color = RealityCardBg, shape = RoundedCornerShape(12.dp), border = BorderStroke(1.dp, RealityCardBorder), modifier = Modifier.fillMaxWidth()) {
            Row(modifier = Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Fake RST (Эксперимент)", color = Color.White, fontSize = 18.sp)
                    Text("Кидает ложные RST провайдеру", color = Color.Gray, fontSize = 12.sp)
                }
                Switch(checked = fakeRST, onCheckedChange = { fakeRST = it }, colors = SwitchDefaults.colors(checkedThumbColor = RealityNeonGreen, checkedTrackColor = Color(0xFF1E2125)))
            }
        }
    }
}

@Composable
fun LogsScreen() {
    val logs = LogManager.logs
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current

    // Автоскролл к последней строчке при добавлении новых логов
    LaunchedEffect(logs.size) {
        if (logs.isNotEmpty()) {
            listState.animateScrollToItem(logs.size - 1)
        }
    }

    Column(modifier = Modifier.padding(16.dp).fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 10.dp, bottom = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "Логи подключения",
                color = RealityCyan,
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold
            )
            
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // Кнопка Копировать
                Button(
                    onClick = {
                        val fullLogText = logs.joinToString("\n") { it.original }
                        clipboardManager.setText(AnnotatedString(fullLogText))
                        Toast.makeText(context, "Логи скопированы!", Toast.LENGTH_SHORT).show()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = RealityCardBg),
                    border = BorderStroke(1.dp, RealityCardBorder),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("📋 Копировать", color = RealityCyan, fontSize = 12.sp)
                }

                // Кнопка Очистить
                Button(
                    onClick = {
                        LogManager.clearLogs()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = RealityCardBg),
                    border = BorderStroke(1.dp, Color(0xFFFF4C4C).copy(alpha = 0.5f)),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("🗑️ Очистить", color = Color(0xFFFF4C4C), fontSize = 12.sp)
                }
            }
        }

        Surface(
            color = RealityCardBg,
            shape = RoundedCornerShape(12.dp),
            border = BorderStroke(1.dp, RealityCardBorder),
            modifier = Modifier.fillMaxSize().weight(1f)
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
