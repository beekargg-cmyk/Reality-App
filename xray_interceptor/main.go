package main

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

func main() {
	// Как нужно будет назвать оригинальный экзешник
	const realXrayName = "xray_real.exe"

	// Узнаем, откуда мы запущены
	exePath, err := os.Executable()
	if err != nil {
		exePath = "."
	}
	currentDir := filepath.Dir(exePath)
	
	// Файл, куда будем скидывать все перехваченные данные
	logFile := filepath.Join(currentDir, "intercepted_config.log")

	// Открываем лог
	f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		defer f.Close()
		fmt.Fprintf(f, "\n\n=========================================\n")
		fmt.Fprintf(f, "Time: %s\n", time.Now().Format(time.RFC3339))
		fmt.Fprintf(f, "Args: %v\n", os.Args)
	}

	// Подготавливаем запуск оригинального Xray
	args := os.Args[1:] // пропускаем имя самого экзешника
	realExecPath := filepath.Join(currentDir, realXrayName)

	cmd := exec.Command(realExecPath, args...)

	// ШАГ 1: Ищем конфиги, которые переданы через аргументы файлов (например -config conf.json)
	for i, arg := range args {
		if (arg == "-config" || arg == "-c") && i+1 < len(args) {
			configname := args[i+1]
			content, err := os.ReadFile(configname)
			if err == nil && f != nil {
				fmt.Fprintf(f, "\n[ФАЙЛ КОНФИГА: %s]\n%s\n", configname, string(content))
			}
		}
	}

	// ШАГ 2: Перехватываем STDIN (Туда чаще всего шлют JSON без файлов)
	var stdinBuf bytes.Buffer
	// TeeReader будет читать из оригинального STDIN всё, 
	// что запрашивает xray_real, и параллельно копировать это нам в stdinBuf
	teeStdin := io.TeeReader(os.Stdin, &stdinBuf)
	
	cmd.Stdin = teeStdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	// Запускаем реальный процесс
	err = cmd.Start()
	if err != nil {
		if f != nil {
			fmt.Fprintf(f, "ОШИБКА ЗАПУСКА %s: %v\n", realXrayName, err)
		}
		// Если не нашли реальный xray, завершаемся
		os.Exit(1) 
	}

	// Конфиг часто загружается в первые миллисекунды. 
	// Сохраняем дамп STDIN через пару секунд, пока процесс еще работает.
	go func() {
		time.Sleep(2 * time.Second)
		if f != nil {
			fmt.Fprintf(f, "\n[STDIN ДАМП (при запуске)]:\n%s\n", stdinBuf.String())
			f.Sync()
		}
	}()

	// Ждем, пока VPN отключится или xray завершит работу
	cmd.Wait()

	// На всякий случай пишем финальный дамп
	if f != nil {
		fmt.Fprintf(f, "\n[ПРОЦЕСС ЗАВЕРШЕН. Финальный STDIN]:\n%s\n", stdinBuf.String())
	}
}
