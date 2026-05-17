package vpncore

import (
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"strings"
	"sync"
	"time"
)

// ProbeTarget — цель для сканирования
type ProbeTarget struct {
	Name    string
	IP      string
	Port    string
	TestTLS bool // Если true — пробуем TLS handshake, а не просто TCP
}

// ProbeResult — результат теста одной цели
type ProbeResult struct {
	Name    string
	IP      string
	Status  string // "OPEN", "FILTERED", "TIMEOUT", "RST", "TLS_OK", "TLS_FAIL"
	Ms      int
	Details string
}

// getProbeTargets возвращает список целей для сканирования
// Это все "священные коровы" российского интернета
func getProbeTargets() []ProbeTarget {
	return []ProbeTarget{
		// === РОССИЙСКИЕ ОБЛАКА ===
		{"Yandex Cloud", "51.250.0.1", "443", true},
		{"Yandex Cloud 2", "158.160.0.1", "443", true},
		{"Yandex Cloud 3", "84.201.128.1", "443", true},
		{"VK Cloud", "89.208.84.1", "443", true},
		{"VK Cloud 2", "95.142.192.1", "443", false},
		{"Selectel", "188.93.16.1", "443", true},
		{"Selectel 2", "46.19.36.1", "443", false},
		{"Rostelecom Cloud", "93.158.0.1", "443", false},

		// === БАНКИ (СВЯЩЕННОЕ!) ===
		{"Sberbank API", "194.186.207.1", "443", true},
		{"Tinkoff CDN", "91.194.226.1", "443", true},
		{"VTB Online", "95.213.192.1", "443", false},

		// === CDN / ДОСТАВКА КОНТЕНТА ===
		{"Cloudflare", "188.114.96.1", "443", true},
		{"Cloudflare 2", "104.16.0.1", "443", true},
		{"Cloudflare 3", "172.67.0.1", "443", true},
		{"Fastly CDN", "151.101.0.1", "443", true},
		{"Akamai", "95.100.178.1", "443", true},
		{"Google CDN", "142.250.0.1", "443", true},
		{"Microsoft CDN", "13.107.0.1", "443", true},
		{"Amazon CF", "52.84.0.1", "443", true},
		{"Ngenix (RU CDN)", "185.71.76.1", "443", false},
		{"CDNvideo (RU)", "92.223.68.1", "443", false},
		{"G-Core Labs", "92.223.96.1", "443", true},

		// === СОЦСЕТИ / МЕССЕНДЖЕРЫ ===
		{"VK Main", "87.240.137.164", "443", true},
		{"VK CDN", "95.142.204.1", "443", false},
		{"OK.ru", "217.20.145.1", "443", true},
		{"Mail.ru", "94.100.180.1", "443", true},
		{"Yandex Main", "77.88.55.60", "443", true},
		{"Yandex DNS", "77.88.8.8", "53", false},

		// === ОБНОВЛЕНИЯ ОС ===
		{"Microsoft Update", "13.107.4.50", "443", true},
		{"Apple", "17.253.144.10", "443", true},
		{"Huawei Mobile", "119.8.0.1", "443", false},
		{"Samsung", "34.36.0.1", "443", false},

		// === ИГРЫ ===
		{"Steam", "155.133.248.1", "443", true},
		{"Steam CDN", "23.55.161.1", "443", false},
		{"Epic Games", "34.120.0.1", "443", false},

		// === DNS СЕРВЕРЫ ===
		{"Google DNS", "8.8.8.8", "53", false},
		{"Cloudflare DNS", "1.1.1.1", "53", false},
		{"Yandex DNS DoH", "77.88.8.8", "443", true},
		{"Quad9 DNS", "9.9.9.9", "53", false},
		{"AdGuard DNS", "94.140.14.14", "53", false},

		// === СЕРТИФИКАТЫ / OCSP ===
		{"DigiCert OCSP", "93.184.220.29", "80", false},
		{"Let's Encrypt", "172.65.32.248", "443", true},

		// === ХОСТИНГИ (где VPN живут) ===
		{"Hetzner DE", "88.198.0.1", "443", false},
		{"DigitalOcean", "64.225.0.1", "443", false},
		{"Vultr", "45.32.0.1", "443", false},
		{"OVH", "51.38.0.1", "443", false},
		{"Linode", "172.104.0.1", "443", false},
		{"Scaleway", "51.15.0.1", "443", false},
		{"Oracle Cloud", "132.145.0.1", "443", false},
		{"Azure", "52.178.0.1", "443", true},

		// === НЕСТАНДАРТНЫЕ ПОРТЫ ===
		{"Cloudflare :8443", "188.114.96.1", "8443", false},
		{"Cloudflare :2053", "188.114.96.1", "2053", false},
		{"Cloudflare :2083", "188.114.96.1", "2083", false},
		{"Cloudflare :2087", "188.114.96.1", "2087", false},
		{"VK :8080", "87.240.137.164", "8080", false},
		{"Yandex :8080", "77.88.55.60", "8080", false},
	}
}

// ScanWhitelistedNetworks — главная функция сканирования.
// Вызывается из Kotlin: Vpncore.scanWhitelistedNetworks()
// Возвращает строку-отчёт
func ScanWhitelistedNetworks() string {
	targets := getProbeTargets()
	results := make([]ProbeResult, len(targets))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 10) // Ограничим параллелизм до 10

	fmt.Printf("[СКАНЕР] Запуск. Целей: %d\n", len(targets))

	for i, target := range targets {
		wg.Add(1)
		go func(idx int, t ProbeTarget) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			results[idx] = probeTarget(t)
			fmt.Printf("[СКАНЕР] %s (%s:%s) → %s (%dms)\n",
				results[idx].Name, t.IP, t.Port, results[idx].Status, results[idx].Ms)
		}(i, target)
	}

	wg.Wait()

	// Формируем отчёт
	var sb strings.Builder
	sb.WriteString("=== РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ СЕТИ ===\n\n")

	// Сначала открытые
	sb.WriteString("--- ДОСТУПНЫЕ (можно использовать как relay) ---\n")
	for _, r := range results {
		if r.Status == "OPEN" || r.Status == "TLS_OK" {
			sb.WriteString(fmt.Sprintf("  ✅ %-25s %-18s %s (%dms) %s\n",
				r.Name, r.IP, r.Status, r.Ms, r.Details))
		}
	}

	sb.WriteString("\n--- ЗАБЛОКИРОВАННЫЕ ---\n")
	for _, r := range results {
		if r.Status == "TIMEOUT" || r.Status == "FILTERED" {
			sb.WriteString(fmt.Sprintf("  ❌ %-25s %-18s %s (%dms)\n",
				r.Name, r.IP, r.Status, r.Ms))
		}
	}

	sb.WriteString("\n--- RST (активная блокировка DPI) ---\n")
	for _, r := range results {
		if r.Status == "RST" || r.Status == "TLS_FAIL" {
			sb.WriteString(fmt.Sprintf("  🔴 %-25s %-18s %s (%dms) %s\n",
				r.Name, r.IP, r.Status, r.Ms, r.Details))
		}
	}

	sb.WriteString("\n--- ОШИБКИ ---\n")
	for _, r := range results {
		if r.Status == "ERROR" {
			sb.WriteString(fmt.Sprintf("  ⚠️  %-25s %-18s %s: %s\n",
				r.Name, r.IP, r.Status, r.Details))
		}
	}

	// Считаем статистику
	open := 0
	blocked := 0
	rst := 0
	for _, r := range results {
		switch r.Status {
		case "OPEN", "TLS_OK":
			open++
		case "TIMEOUT", "FILTERED":
			blocked++
		case "RST", "TLS_FAIL":
			rst++
		}
	}
	sb.WriteString(fmt.Sprintf("\n=== ИТОГО: ✅ Открыто: %d | ❌ Заблокировано: %d | 🔴 RST: %d ===\n", open, blocked, rst))

	result := sb.String()
	fmt.Println(result)
	return result
}

func probeTarget(t ProbeTarget) ProbeResult {
	addr := net.JoinHostPort(t.IP, t.Port)
	timeout := 5 * time.Second

	start := time.Now()
	conn, err := net.DialTimeout("tcp", addr, timeout)
	ms := int(time.Since(start).Milliseconds())

	if err != nil {
		if isTimeout(err) {
			return ProbeResult{t.Name, t.IP, "TIMEOUT", ms, ""}
		}
		errStr := err.Error()
		if strings.Contains(errStr, "refused") || strings.Contains(errStr, "reset") {
			return ProbeResult{t.Name, t.IP, "RST", ms, errStr}
		}
		return ProbeResult{t.Name, t.IP, "ERROR", ms, errStr}
	}
	defer conn.Close()

	// TCP прошёл. Если нужен TLS — пробуем
	if t.TestTLS {
		tlsConn := tls.Client(conn, &tls.Config{
			InsecureSkipVerify: true,
			ServerName:         t.IP,
		})
		ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
		defer cancel()

		err = tlsConn.HandshakeContext(ctx)
		ms = int(time.Since(start).Milliseconds())
		if err != nil {
			return ProbeResult{t.Name, t.IP, "TLS_FAIL", ms, err.Error()}
		}
		tlsConn.Close()
		return ProbeResult{t.Name, t.IP, "TLS_OK", ms, ""}
	}

	return ProbeResult{t.Name, t.IP, "OPEN", ms, ""}
}
