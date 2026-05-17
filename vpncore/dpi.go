package vpncore

import (
	"fmt"
	"net"
	"time"
)

var (
	// EnableDPIFragmentation - включает/выключает разбиение ClientHello на части
	EnableDPIFragmentation bool = false
	// EnableFakeRST - включает логику подмены/сброса левых RST пакетов
	EnableFakeRST bool = false
)

// SetDPISettings вызывается из Kotlin при переключении ползунков
func SetDPISettings(fragmentation bool, fakeRst bool) {
	EnableDPIFragmentation = fragmentation
	EnableFakeRST = fakeRst
	fmt.Printf("[DPI] Фрагментация: %v, Fake RST: %v\n", fragmentation, fakeRst)
}

// dpiFragmentationConn - наша "обёртка" вокруг реального интернет-соединения.
// Если трафик идёт напрямую к сайту (не через VLESS), мы можем обмануть DPI
// разбив первый пакет (ClientHello) на мелкие части.
type dpiFragmentationConn struct {
	net.Conn // Встраиваем стандартный интерфейс соединения
}

// Write перехватывает процесс отправки байтов в интернет.
// Это и есть то место, где работает мини-фича обхода фейковых пакетов от DPI!
func (c *dpiFragmentationConn) Write(b []byte) (int, error) {
	// Представим, что b - это пакет ClientHello (начало установки HTTPS-соединения).
	// DPI провайдера ждет именно этот пакет целиком, чтобы прочитать внутри
	// имя заблокированного сайта и прислать нам фейковый RST.
	
	// Наша супер-фича: мы просто разбиваем этот кусок данных (буфер 'b')!
	if EnableDPIFragmentation && len(b) > 10 { // Если пакет достаточно большой
		fmt.Println("DPI Bypass: Замечен большой пакет! Фрагментируем...")
		
		// 1. Отправляем только первые 5 байт (этого мало, DPI не поймет что это)
		part1 := b[:5]
		n1, err := c.Conn.Write(part1)
		if err != nil {
			return n1, err
		}

		// 2. Ждем совсем чуть-чуть, чтобы пакеты однозначно легли в разные кадры сети
		time.Sleep(1 * time.Millisecond)

		// 3. Отправляем остаток (тут лежит домен, но он уже оторван от начала)
		// У DPI провайдера просто не хватит хитрости (или памяти) собрать их вместе!
		part2 := b[5:]
		n2, err := c.Conn.Write(part2)
		
		// Возвращаем общее количество отправленных байтов
		return n1 + n2, err
	}

	// Если пакет маленький, отправляем как есть
	return c.Conn.Write(b)
}

// DialWithFragment — наша кастомная функция подключения к интернету.
// Если мы хотим открыть соединение в обход DPI напрямую, мы используем её.
func DialWithFragment(network, address string) (net.Conn, error) {
	fmt.Printf("Подключаемся к %s напрямую с фрагментацией...\n", address)
	
	// Устанавливаем обычное соединение с сервером (например instagram.com:443)
	conn, err := net.Dial(network, address)
	if err != nil {
		return nil, err
	}
	
	// Оборачиваем это соединение в нашу хитрую штуку
	return &dpiFragmentationConn{Conn: conn}, nil
}
