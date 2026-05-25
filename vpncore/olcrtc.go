package vpncore

import (
	"fmt"

	"github.com/openlibrecommunity/olcrtc/mobile"
)

var isOlcRTCRunning bool

// StartOlcRTCProxy запускает локальный SOCKS5 прокси через выбранного провайдера WebRTC
func StartOlcRTCProxy(carrier string, transport string, roomID string, keyHex string) error {
	if isOlcRTCRunning {
		fmt.Println("OlcRTC уже запущен!")
		return nil
	}

	fmt.Printf("Инициализация OlcRTC (Carrier: %s, Transport: %s)...\n", carrier, transport)

	// 1. Инициализируем провайдеров и настраиваем транспорт
	mobile.SetProviders()
	mobile.SetDebug(true)
	mobile.SetTransport(transport)
	mobile.SetVP8Options(60, 64)
	mobile.SetDNS("77.88.8.8:53")

	// 2. Стартуем (локальный порт SOCKS5 = 10809, чтобы не конфликтовать с Xray, если что)
	// carrierName = carrier (telemost, wbstream и т.д.), clientID = "v2raytun"
	err := mobile.Start(carrier, roomID, "v2raytun", keyHex, 10809, "", "")
	if err != nil {
		return fmt.Errorf("ошибка запуска OlcRTC: %v", err)
	}

	// 3. Ждем, пока WebRTC канал установится (таймаут 15 секунд)
	fmt.Println("Ожидание готовности OlcRTC...")
	err = mobile.WaitReady(15000)
	if err != nil {
		mobile.Stop()
		return fmt.Errorf("OlcRTC не смог подключиться: %v", err)
	}

	fmt.Println("===== OlcRTC SOCKS5 ПРОКСИ УСПЕШНО ЗАПУЩЕН НА 127.0.0.1:10809 =====")
	isOlcRTCRunning = true
	return nil
}

// StopOlcRTCProxy останавливает WebRTC туннель
func StopOlcRTCProxy() {
	if isOlcRTCRunning {
		mobile.Stop()
		isOlcRTCRunning = false
		fmt.Println("OlcRTC остановлен.")
	}
}
