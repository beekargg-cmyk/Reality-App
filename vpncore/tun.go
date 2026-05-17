package vpncore

import (
	"fmt"
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
	// Экспериментальная фича: Сброс (drop) фейковых RST пакетов 
	// Мы анализируем сырые IP пакеты и дропаем те, в которых взведен флаг TCP RST.
	if EnableFakeRST && len(b) >= 20 {
		version := b[0] >> 4
		
		if version == 4 { // Обработка IPv4
			ihl := (b[0] & 0x0F) * 4
			protocol := b[9]
			
			// Если пакет - TCP (6) и имеет достаточную длину
			if protocol == 6 && len(b) >= int(ihl)+14 {
				tcpFlags := b[ihl+13]
				isRST := (tcpFlags & 0x04) != 0 // Маска 0x04 (00000100) вытаскивает флаг RST
				
				if isRST {
					fmt.Println("[TUN-DPI] IPv4: Заблокирован входящий RST пакет!")
					// Возвращаем длину пакета, словно он успешно доставлен (но он исчезает в пустоте)
					return len(b), nil
				}
			}
		} else if version == 6 && len(b) >= 54 { // Обработка IPv6 (заголовок всегда 40 байт + TCP)
			protocol := b[6] // Поле Next Header в заголовке IPv6
			
			if protocol == 6 { // TCP
				tcpFlags := b[40+13]
				isRST := (tcpFlags & 0x04) != 0
				
				if isRST {
					fmt.Println("[TUN-DPI] IPv6: Заблокирован входящий RST пакет!")
					return len(b), nil
				}
			}
		}
	}

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
