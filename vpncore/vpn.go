package vpncore

import (
	"fmt"

	_ "golang.org/x/mobile/bind"
	"github.com/xjasonlyu/tun2socks/v2/engine"
)

// StartVPN - главная точка входа для Android!
func StartVPN(fd int, vlessLink string) {
	fmt.Printf("[ОСНОВНОЕ ЯДРО] Android передал FD=%d\n", fd)
	
	// 1. Запускаем "мотор" (Xray) - он слушает SOCKS5 на порту 10808
	err := StartXrayEngine(vlessLink)
	if err != nil {
		fmt.Printf("[ОШИБКА] Не удалось запустить Xray: %v\n", err)
		return
	}

	// 2. Запускаем tun2socks (перехватывает пакеты из Android FD и кидает в наш локальный SOCKS5)
	fmt.Println("[ЯДРО] Запускаем туннелирование (TUN -> SOCKS5)...")
	go func() {
		key := &engine.Key{
			Proxy:    "socks5://127.0.0.1:10808", // Куда кидаем (открыт Xray-core)
			Device:   fmt.Sprintf("fd://%d", fd),   // Откуда берем (Android VPN Service)
			LogLevel: "debug",
		}
		engine.Insert(key)
		engine.Start()
	}()

	fmt.Println("===== MAINFRAME ONLINE: ЯДРО XRAY С МАРШРУТИЗАЦИЕЙ ЗАПУЩЕНО! =====")
}

// StopVPN - мягкая остановка
func StopVPN() {
	fmt.Println("Остановка сервисов...")
	// Глушим Xray-core
	StopXrayEngine()
	// Глушим маршрутизацию tun2socks
	engine.Stop()
	fmt.Println("VPN полностью остановлен.")
}
