package vpncore

import (
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"strings"
	"time"
)

// DiagResult — результат одной проверки
type DiagResult struct {
	Test    string
	Status  string // "OK", "BLOCKED", "TIMEOUT", "ERROR"
	Details string
	Ms      int
}

// RunFullDiagnostics — запускает полную диагностику сети и возвращает JSON-строку с результатами.
// Вызывается из Kotlin: Vpncore.runFullDiagnostics()
func RunFullDiagnostics() string {
	var results []string

	// ========== 1. TCP PING К КЛЮЧЕВЫМ IP ==========
	fmt.Println("[ДИАГНОСТИКА] Запуск...")

	// Российские сервисы
	results = append(results, testTCPPing("Яндекс (77.88.55.60:443)", "77.88.55.60:443"))
	results = append(results, testTCPPing("Mail.ru (94.100.180.200:443)", "94.100.180.200:443"))
	results = append(results, testTCPPing("VK (87.240.137.164:443)", "87.240.137.164:443"))

	// Зарубежные сервисы
	results = append(results, testTCPPing("Google (142.250.74.46:443)", "142.250.74.46:443"))
	results = append(results, testTCPPing("Cloudflare (1.1.1.1:443)", "1.1.1.1:443"))
	results = append(results, testTCPPing("Cloudflare (104.16.132.229:443)", "104.16.132.229:443"))
	results = append(results, testTCPPing("Microsoft (13.107.42.14:443)", "13.107.42.14:443"))
	results = append(results, testTCPPing("Apple (17.253.144.10:443)", "17.253.144.10:443"))
	results = append(results, testTCPPing("Amazon AWS (52.94.236.248:443)", "52.94.236.248:443"))

	// ========== 2. DNS РЕЗОЛВИНГ ЧЕРЕЗ РАЗНЫЕ СЕРВЕРЫ ==========
	results = append(results, testDNS("DNS Яндекс", "77.88.8.8:53", "ya.ru"))
	results = append(results, testDNS("DNS Google", "8.8.8.8:53", "google.com"))
	results = append(results, testDNS("DNS Cloudflare", "1.1.1.1:53", "cloudflare.com"))
	results = append(results, testDNS("DNS провайдер (системный)", "", "ya.ru"))

	// ========== 3. HTTPS (TLS HANDSHAKE) К CDN ==========
	results = append(results, testHTTPS("HTTPS Cloudflare CDN", "cloudflare-dns.com"))
	results = append(results, testHTTPS("HTTPS Google", "www.google.com"))
	results = append(results, testHTTPS("HTTPS Яндекс", "ya.ru"))
	results = append(results, testHTTPS("HTTPS GitHub", "github.com"))

	// ========== 4. ПРОВЕРКА DNS HIJACK ==========
	results = append(results, testDNSHijack())

	output := strings.Join(results, "\n")
	fmt.Println("[ДИАГНОСТИКА] Завершена!")
	fmt.Println(output)
	return output
}

func testTCPPing(name, addr string) string {
	start := time.Now()
	conn, err := net.DialTimeout("tcp", addr, 4*time.Second)
	ms := int(time.Since(start).Milliseconds())

	if err != nil {
		if isTimeout(err) {
			return fmt.Sprintf("❌ %s | TIMEOUT (%dms) | Пакеты не доходят — IP заблокирован или недоступен", name, ms)
		}
		return fmt.Sprintf("❌ %s | ERROR (%dms) | %s", name, ms, err.Error())
	}
	conn.Close()
	return fmt.Sprintf("✅ %s | OK (%dms)", name, ms)
}

func testDNS(name, server, domain string) string {
	var resolver *net.Resolver

	if server == "" {
		// Системный DNS
		resolver = net.DefaultResolver
	} else {
		resolver = &net.Resolver{
			PreferGo: true,
			Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
				d := net.Dialer{Timeout: 4 * time.Second}
				return d.DialContext(ctx, "udp", server)
			},
		}
	}

	start := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	addrs, err := resolver.LookupHost(ctx, domain)
	ms := int(time.Since(start).Milliseconds())

	if err != nil {
		if isTimeout(err) {
			return fmt.Sprintf("❌ %s | TIMEOUT (%dms) | DNS-сервер недоступен — заблокирован или перехвачен", name, ms)
		}
		return fmt.Sprintf("❌ %s | ERROR (%dms) | %s", name, ms, err.Error())
	}

	ip := ""
	if len(addrs) > 0 {
		ip = addrs[0]
	}
	return fmt.Sprintf("✅ %s | OK (%dms) | %s → %s", name, ms, domain, ip)
}

func testHTTPS(name, host string) string {
	start := time.Now()

	conn, err := tls.DialWithDialer(
		&net.Dialer{Timeout: 5 * time.Second},
		"tcp",
		host+":443",
		&tls.Config{ServerName: host},
	)
	ms := int(time.Since(start).Milliseconds())

	if err != nil {
		if isTimeout(err) {
			return fmt.Sprintf("❌ %s | TIMEOUT (%dms) | TLS-хэндшейк не прошёл — DPI блокирует или IP недоступен", name, ms)
		}
		// Проверяем, не RST ли это
		errStr := err.Error()
		if strings.Contains(errStr, "reset") || strings.Contains(errStr, "refused") {
			return fmt.Sprintf("🔴 %s | RST (%dms) | Провайдер СБРОСИЛ соединение (DPI-блокировка!)", name, ms)
		}
		return fmt.Sprintf("❌ %s | ERROR (%dms) | %s", name, ms, errStr)
	}
	conn.Close()
	return fmt.Sprintf("✅ %s | OK (%dms) | TLS рукопожатие прошло успешно", name, ms)
}

func testDNSHijack() string {
	// Идея: резолвим один и тот же домен через Google DNS и через Яндекс DNS.
	// Если ответы одинаковые — ок. Если разные — возможен DNS hijack.
	googleResolver := &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
			d := net.Dialer{Timeout: 4 * time.Second}
			return d.DialContext(ctx, "udp", "8.8.8.8:53")
		},
	}

	yandexResolver := &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
			d := net.Dialer{Timeout: 4 * time.Second}
			return d.DialContext(ctx, "udp", "77.88.8.8:53")
		},
	}

	domain := "google.com"

	hCtx, hCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer hCancel()
	gAddrs, gErr := googleResolver.LookupHost(hCtx, domain)
	yAddrs, yErr := yandexResolver.LookupHost(hCtx, domain)

	if gErr != nil && yErr != nil {
		return "⚠️  DNS Hijack тест | Оба DNS недоступны — невозможно проверить"
	}
	if gErr != nil {
		return "⚠️  DNS Hijack тест | Google DNS заблокирован, Яндекс DNS работает — возможен whitelist DNS"
	}
	if yErr != nil {
		return "⚠️  DNS Hijack тест | Яндекс DNS заблокирован — нестандартная ситуация"
	}

	gIP := ""
	yIP := ""
	if len(gAddrs) > 0 {
		gIP = gAddrs[0]
	}
	if len(yAddrs) > 0 {
		yIP = yAddrs[0]
	}

	if gIP == yIP {
		return fmt.Sprintf("✅ DNS Hijack тест | Ответы совпадают (%s) — DNS НЕ перехвачен", gIP)
	}
	return fmt.Sprintf("⚠️  DNS Hijack тест | Google=%s, Яндекс=%s — ответы РАЗНЫЕ, возможен DNS перехват", gIP, yIP)
}

func isTimeout(err error) bool {
	if err == nil {
		return false
	}
	e, ok := err.(net.Error)
	return ok && e.Timeout()
}
