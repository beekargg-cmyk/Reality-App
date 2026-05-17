package vpncore

import (
	"math/rand"
	"net"
)

// MyCustomProtocolConn - это наш СОБСТВЕННЫЙ протокол!
// Берем обычное TCP соединение и превращаем его в невидимое для DPI.
type MyCustomProtocolConn struct {
	net.Conn
	secretKey byte // Ключ для простейшего шифрования
}

// Write - когда мы отправляем данные в интернет
func (c *MyCustomProtocolConn) Write(b []byte) (int, error) {
	// Создаем буфер такого же размера
	obfuscated := make([]byte, len(b))
	
	for i := 0; i < len(b); i++ {
		// Шифруем каждый байт с помощью операции XOR (Исключающее ИЛИ)
		// Для DPI это будет выглядеть как абсолютно случайный мусор (белый шум)
		// Никаких хендшейков TLS, никаких SNI, никаких паттернов VLESS!
		obfuscated[i] = b[i] ^ c.secretKey
	}

	// Отправляем мусор провайдеру
	return c.Conn.Write(obfuscated)
}

// Read - когда мы получаем данные от нашего сервера
func (c *MyCustomProtocolConn) Read(b []byte) (int, error) {
	// Читаем зашифрованные данные из интернета
	n, err := c.Conn.Read(b)
	if err != nil {
		return n, err
	}

	for i := 0; i < n; i++ {
		// Расшифровываем тем же ключом (в XOR шифруется и расшифровывается одинаково)
		b[i] = b[i] ^ c.secretKey
	}

	return n, nil
}

// DialCustomProtocol — функция, которая первой стучится к нам на сервер.
func DialCustomProtocol(address string) (net.Conn, error) {
	// Подключаемся к нашему серверу (VPS)
	conn, err := net.Dial("tcp", address)
	if err != nil {
		return nil, err
	}

	// Чтобы DPI не вычислял нас по одинаковым размерам пакетов (тайминги и длины),
	// мы можем перед началом общения отправлять случайное количество мусорных байт!
	randomPaddingSize := rand.Intn(100) + 50 // от 50 до 150 байт мусора
	garbage := make([]byte, randomPaddingSize)
	rand.Read(garbage)
	
	// Отправляем мусор первым делом, путая эвристику (косвенные признаки) DPI
	conn.Write(garbage)

	// Возвращаем наш защищенный сокет
	return &MyCustomProtocolConn{
		Conn:      conn,
		secretKey: 0x42, // Наш секретный ключ-байт
	}, nil
}
