package vpncore

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// FetchSubscription скачивает подписку по URL, парсит все ссылки
// и возвращает список серверов в формате JSON (чтобы Kotlin смог легко нарисовать кнопочки).
func FetchSubscription(subUrl string) (string, error) {
	fmt.Println("Начинаем скачивать подписку:", subUrl)

	// Шаг 1: Если ссылка начинается с кастомного happ://add/https://, нам нужно вырезать чистый HTTP
	if strings.HasPrefix(subUrl, "happ://add/") {
		subUrl = strings.TrimPrefix(subUrl, "happ://add/")
	}

	// Шаг 2: Делаем HTTP-запрос к серверу биллинга
	resp, err := http.Get(subUrl)
	if err != nil {
		return "", fmt.Errorf("ошибка при скачивании подписки: %v", err)
	}
	// Отложенное закрытие (сработает автоматически в конце функции)
	defer resp.Body.Close()

	// Шаг 3: Читаем ответ сервера в виде массива байт
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("ошибка чтения ответа: %v", err)
	}

	// Обычно сервер Xray/V2ray отдает ссылки закодированными в Base64.
	// Шаг 4: Пытаемся раскодировать Base64.
	// В Go мы можем использовать разные декодеры (StdEncoding или URLEncoding).
	decodedBytes, err := base64.StdEncoding.DecodeString(string(body))
	if err != nil {
		// Если не удалось - возможно сервер отдал ссылки прямо обычным текстом (каждая с новой строки)
		decodedBytes = body 
	}

	rawText := string(decodedBytes)
	
	// Шаг 5: Разбиваем текст на строки (каждая строка - это 'vless://...')
	lines := strings.Split(rawText, "\n")

	var servers []VlessConfig // Создаем пустой массив (срез) из наших настроек серверов

	for _, line := range lines {
		line = strings.TrimSpace(line) // Убираем пробелы и лишние скрытые символы по краям
		if line == "" {
			continue // Пропускаем пустые строки
		}

		// Используем нашу функцию ParseVlessLink из xray.go!
		config, err := ParseVlessLink(line)
		if err == nil && config != nil {
			servers = append(servers, *config) // Если ссылка валидная, добавляем её в список
		}
	}

	// Шаг 6: Инструмент `gomobile` не умеет напрямую передавать сложные массивы структур в Kotlin.
	// Поэтому мы запаковываем наш массив обратно в обычную строку (JSON), 
	// а Kotlin её легко распакует и покажет "кучу локаций".
	jsonResult, err := json.Marshal(servers)
	if err != nil {
		return "", fmt.Errorf("ошибка создания JSON: %v", err)
	}

	fmt.Printf("Успешно распарсено %d серверов из подписки!\n", len(servers))
	return string(jsonResult), nil
}
