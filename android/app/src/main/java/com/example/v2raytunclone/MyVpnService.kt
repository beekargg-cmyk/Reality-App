package com.example.v2raytunclone

import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log
import vpncore.Vpncore

class MyVpnService : VpnService() {

    companion object {
        var isServiceRunning = false
    }

    private var vpnInterface: ParcelFileDescriptor? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action

        // Получаем ссылку, которую кидает MainActivity при клике на "ПОДКЛЮЧИТЬ"
        val selectedLink = intent?.getStringExtra("VLESS_LINK") ?: ""

        if (action == "START_VPN") {
            startVpnTunnel(selectedLink)
        } else if (action == "STOP_VPN") {
            stopVpnTunnel()
        }
        return START_NOT_STICKY
    }

    private fun startVpnTunnel(link: String) {
        if (vpnInterface != null) {
            Log.d("VPN", "Туннель уже работает!")
            return
        }

        if (link.isEmpty()) {
            Log.e("VPN", "ОШИБКА: Сервер не выбран или ссылка пустая!")
            return
        }

        Log.d("VPN", "Настройка VPN интерфейса...")

        try {
            val builder = Builder()
            builder.setSession("HappV2ray")
            builder.setMtu(1500)
            builder.addAddress("10.0.0.2", 32)
            builder.addRoute("0.0.0.0", 0) // Перехватываем ВЕСЬ интернет

            // ДОБАВЬ ВОТ ЭТИ 2 СТРОЧКИ: Скажем Андроиду, как переводить имена сайтов в IP
            builder.addDnsServer("1.1.1.1")
            builder.addDnsServer("8.8.8.8")

            // ВОТ ЭТО РАСКОММЕНТИРУЙ!!! Разрешаем нашему приложению и Xray-ядру гулять мимо VPN в чистый интернет!
            builder.addDisallowedApplication(packageName)

            vpnInterface = builder.establish()

            val fd = vpnInterface?.fd ?: -1
            Log.d("VPN", "Интерфейс упешно создан! FD = $fd")

            if (fd != -1) {
                isServiceRunning = true
                Log.d("VPN", "Передаем карточку интерфейса (FD) и ссылку в ядро GO...")

                // Запускаем тяжелый процесс ядра в отдельном фоновом потоке
                Thread {
                    try {
                        Vpncore.startVPN(fd.toLong(), link)
                        Log.d("VPN", "Внимание: Движок GO УСПЕШНО ВКЛЮЧЕН!")
                    } catch (e: Exception) {
                        Log.e("VPN", "Ошибка запуска Go-ядра: ${e.message}")
                    }
                }.start()
            }
        } catch (e: Exception) {
            Log.e("VPN", "Ошибка создания туннеля Android: ${e.message}")
        }
    }

    private fun stopVpnTunnel() {
        Log.d("VPN", "Остановка VPN...")
        isServiceRunning = false
        try {
            Vpncore.stopVPN()
            vpnInterface?.close()
            vpnInterface = null
            Log.d("VPN", "VPN отключен.")
        } catch (e: Exception) {
            Log.e("VPN", "Ошибка при остановке VPN: ${e.message}")
        }
        stopSelf() // Останавливаем службу телефона
    }

    override fun onDestroy() {
        super.onDestroy()
        stopVpnTunnel()
    }
}
