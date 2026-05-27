package vpncore

import (
	"fmt"
	"strings"
	"runtime/debug"

	_ "golang.org/x/mobile/bind"
	"github.com/xjasonlyu/tun2socks/v2/engine"
)

// StartVPN - главная точка входа для Android!
func StartVPN(fd int, link string) {
	fmt.Printf("[ОСНОВНОЕ ЯДРО] Android передал FD=%d\n", fd)
	
	// Ограничиваем память Go Runtime, чтобы Android не убивал процесс (OOM)
	// Ставим лимит ~150 МБ (Android обычно убивает при 256-512 МБ)
	debug.SetMemoryLimit(150 * 1024 * 1024)
	
	// Проверяем тип протокола
	if strings.HasPrefix(link, "olcrtc://") {
		// Парсим OlcRTC ссылку
		server, err := ParseSubscriptionLine(link)
		if err != nil {
			fmt.Printf("[ОШИБКА] Неверная ссылка OlcRTC: %v\n", err)
			return
		}
		// 1. Запускаем локальный SOCKS5 прокси
		err = StartOlcRTCProxy(server.Carrier, server.Transport, server.RoomID, server.Key)
		if err != nil {
			fmt.Printf("[ОШИБКА] Не удалось запустить OlcRTC: %v\n", err)
			return
		}
		// 2. Запускаем Sing-Box, который стучится в этот локальный прокси
		err = StartSingBoxWithLocalSocks(10809)
		if err != nil {
			fmt.Printf("[ОШИБКА] Не удалось запустить Sing-Box для OlcRTC: %v\n", err)
			return
		}
	} else {
		// Стандартный VLESS или Naive
		err := StartSingBoxEngine(link)
		if err != nil {
			fmt.Printf("[ОШИБКА] Не удалось запустить Sing-Box: %v\n", err)
			return
		}
	}

	// 2. Запускаем tun2socks (перехватывает пакеты из Android FD и кидает в наш локальный SOCKS5)
	fmt.Println("[ЯДРО] Запускаем туннелирование (TUN -> SOCKS5)...")
	go func() {
		key := &engine.Key{
			Proxy:    "socks5://127.0.0.1:10808", // Куда кидаем (открыт Sing-Box SOCKS inbound)
			Device:   fmt.Sprintf("fd://%d", fd),   // Откуда берем (Android VPN Service)
			LogLevel: "debug",
		}
		engine.Insert(key)
		engine.Start()
	}()

	fmt.Println("===== MAINFRAME ONLINE: ЯДРО SING-BOX С МАРШРУТИЗАЦИЕЙ ЗАПУЩЕНО! =====")
}

// StopVPN - мягкая остановка
func StopVPN() {
	fmt.Println("Остановка сервисов...")
	// Глушим Sing-Box
	StopSingBoxEngine()
	// Глушим OlcRTC (если работал)
	StopOlcRTCProxy()
	// Глушим маршрутизацию tun2socks
	engine.Stop()
	fmt.Println("VPN полностью остановлен.")
}
