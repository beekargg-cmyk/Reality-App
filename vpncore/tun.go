package vpncore

import (
	"os"
)

// androidTUN - это наша "труба", которая соединяет Android и наш Go-код.
type androidTUN struct {
	file *os.File
}

// NewAndroidTUN берет число (файловый дескриптор) и превращает его
// в полноценный объект Файла, который Go умеет читать и писать.
func NewAndroidTUN(fd int) *androidTUN {
	// В Unix-системах (и Android) всё является "файлом", в том числе сетевые интерфейсы.
	// uintptr - это указатель. Мы оборачиваем число fd в реальный виртуальный файл системы.
	file := os.NewFile(uintptr(fd), "tun")
	return &androidTUN{
		file: file,
	}
}

// Read сырых сетевых пакетов из телефона
func (t *androidTUN) Read(b []byte) (int, error) {
	// Android отправляет нам пакет
	return t.file.Read(b)
}

// Write (отправка) сырых сетевых пакетов обратно в телефон (в приложения)
func (t *androidTUN) Write(b []byte) (int, error) {
	// Мы прочитали ответ из интернета и возвращаем его в телефон
	return t.file.Write(b)
}

// Close закрывает туннель при остановке VPN
func (t *androidTUN) Close() error {
	if t.file != nil {
		return t.file.Close()
	}
	return nil
}
