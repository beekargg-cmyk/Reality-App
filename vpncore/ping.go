package vpncore

import (
	"fmt"
	"net"
	"net/url"
	"time"
)

// PingServer пытается измерить задержку (TCP ping) до хоста из VLESS ссылки
func PingServer(link string) int {
	// Извлекаем хост и порт из ссылки
	parsedUrl, err := url.Parse(link)
	if err != nil {
		fmt.Println("Ошибка парсинга ссылки для пинга:", err)
		return -1
	}

	host := parsedUrl.Hostname()
	port := parsedUrl.Port()
	if port == "" {
		port = "443" // По умолчанию для reality
	}

	address := net.JoinHostPort(host, port)
	timeout := 3 * time.Second

	start := time.Now()
	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		fmt.Println("Пинг не прошел до", address, ":", err)
		return -1
	}
	defer conn.Close()

	duration := time.Since(start)
	return int(duration.Milliseconds())
}
