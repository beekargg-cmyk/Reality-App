package vpncore

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// V2RayServer — структура для передачи данных о сервере в Kotlin
type V2RayServer struct {
	Title    string `json:"Title"`
	Host     string `json:"Host"`
	Port     int    `json:"Port"`
	FullLink string `json:"FullLink"`
	Protocol string `json:"Protocol"` // "vless", "vmess", "olcrtc"
	// Специфичные поля для VLESS
	UUID     string `json:"UUID"`
	Security string `json:"Security"` // reality, tls
	SNI      string `json:"SNI"`
	Network  string `json:"Network"`  // tcp, ws, xhttp
	Path     string `json:"Path"`     // для ws или xhttp
	// Специфичные поля для OlcRTC (Телемост)
	RoomID    string `json:"RoomID,omitempty"`
	Key       string `json:"Key,omitempty"`
	Carrier   string `json:"Carrier,omitempty"`
	Transport string `json:"Transport,omitempty"`
}

// fetchYandexDiskDirectURL запрашивает прямой URL на скачивание файла через API Яндекса
func fetchYandexDiskDirectURL(publicLink string) (string, error) {
	apiURL := fmt.Sprintf("https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=%s", url.QueryEscape(publicLink))
	resp, err := http.Get(apiURL)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("yandex api status %d: %s", resp.StatusCode, string(body))
	}

	var res struct {
		Href string `json:"href"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return "", err
	}

	if res.Href == "" {
		return "", fmt.Errorf("empty download href")
	}

	return res.Href, nil
}

// FetchSubscription скачивает подписку по URL, парсит все ссылки
// и возвращает список серверов в формате JSON (чтобы Kotlin смог легко нарисовать кнопочки).
func FetchSubscription(subUrl string) (string, error) {
	fmt.Println("Начинаем скачивать подписку:", subUrl)

	// Шаг 1: Если ссылка начинается с кастомного happ://add/https://, нам нужно вырезать чистый HTTP
	if strings.HasPrefix(subUrl, "happ://add/") {
		subUrl = strings.TrimPrefix(subUrl, "happ://add/")
	}

	var resp *http.Response
	var err error

	// Шаг 1.5: Если в качестве подписки вставили ссылку на Яндекс.Диск — обрабатываем её
	isYandexDisk := strings.Contains(subUrl, "disk.yandex.ru") || strings.Contains(subUrl, "yadi.sk") || strings.Contains(subUrl, "disk.yandex.com")
	if isYandexDisk {
		fmt.Println("Обнаружена ссылка Яндекс.Диска, получаем прямой URL...")
		directURL, apiErr := fetchYandexDiskDirectURL(subUrl)
		if apiErr != nil {
			return "", fmt.Errorf("не удалось получить ссылку с Яндекс.Диска: %v", apiErr)
		}
		subUrl = directURL
	}

	// Шаг 2: Делаем HTTP-запрос к серверу
	resp, err = http.Get(subUrl)
	if err != nil {
		// Если запрос к обычному серверу упал, и это была НЕ прямая ссылка Яндекс.Диска,
		// пробуем применить встроенное зеркало (пока вставим временный плейсхолдер)
		if !isYandexDisk {
			fallbackLink := "https://disk.yandex.ru/d/8YDTq4WUq1_idA"
			fmt.Printf("Основной сервер недоступен (%v). Пробуем скачать с зеркала Яндекс.Диска...\n", err)
			directURL, apiErr := fetchYandexDiskDirectURL(fallbackLink)
			if apiErr == nil {
				resp, err = http.Get(directURL)
			} else {
				fmt.Printf("Зеркало Яндекс.Диска тоже недоступно: %v\n", apiErr)
			}
		}
	}

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
	bodyStr := string(body)
	cleanBody := strings.NewReplacer(" ", "", "\n", "", "\r", "", "\t", "").Replace(bodyStr)
	decodedBytes, err := base64.StdEncoding.DecodeString(cleanBody)
	if err != nil {
		// Если не удалось - возможно сервер отдал ссылки прямо обычным текстом (каждая с новой строки)
		decodedBytes = body 
	}

	rawText := string(decodedBytes)
	
	// Шаг 5: Разбиваем текст на строки
	lines := strings.Split(rawText, "\n")

	servers := make([]V2RayServer, 0) // Используем новую структуру, инициализируем пустым массивом!

	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		// Пытаемся распарсить строку
		config, err := ParseSubscriptionLine(line)
		if err == nil && config != nil {
			servers = append(servers, *config)
			fmt.Printf("OlcRTC success: %s\n", config.Title)
		} else {
			fmt.Printf("ParseSubscriptionLine error for %s: %v\n", line, err)
			// Если ParseSubscriptionLine не подошел (например, это обычный vless://),
			// пытаемся распарсить как VLESS через xray.go
			vlessConfig, vlessErr := ParseVlessLink(line)
			if vlessErr == nil && vlessConfig != nil {
				servers = append(servers, V2RayServer{
					Title:    vlessConfig.Title,
					Host:     vlessConfig.Host,
					Port:     0, // Парсится внутри
					FullLink: line, // Сохраняем исходную ссылку
					Protocol: "vless",
					UUID:     vlessConfig.UUID,
					Security: "reality",
					SNI:      vlessConfig.SNI,
					Network:  "tcp",
				})
			} else {
				fmt.Printf("ParseVlessLink error for %s: %v\n", line, vlessErr)
			}
		}
	}

	// Шаг 6: Упаковываем обратно в JSON
	jsonResult, err := json.Marshal(servers)
	if err != nil {
		return "", fmt.Errorf("ошибка создания JSON: %v", err)
	}

	fmt.Printf("Успешно распарсено %d серверов из подписки!\n", len(servers))
	return string(jsonResult), nil
}

// ParseSubscriptionLine разбирает одну строку (vless://... или olcrtc://...)
func ParseSubscriptionLine(line string) (*V2RayServer, error) {
	line = strings.TrimSpace(line)

	// Поддержка OlcRTC (Яндекс.Телемост, Wildberries и др.)
	// Используем Contains и Index, так как HasPrefix может падать из-за BOM или скрытых символов
	if idx := strings.Index(line, "olcrtc://"); idx != -1 {
		// Извлекаем чистую ссылку, отбрасывая мусор в начале (если есть)
		cleanLine := line[idx:]
		body := strings.TrimPrefix(cleanLine, "olcrtc://")
		
		// Отделяем Query параметры (?name=...)
		parts := strings.SplitN(body, "?", 2)
		credentials := parts[0]
		
		var name string = "OlcRTC Bypass"
		var carrier string = "telemost" // По умолчанию telemost
		var transport string = "vp8channel" // По умолчанию vp8channel
		
		if len(parts) > 1 {
			// Парсим query (например, name=Test&carrier=wbstream)
			query, err := url.ParseQuery(parts[1])
			if err == nil {
				if query.Get("name") != "" {
					name = query.Get("name")
				}
				if query.Get("carrier") != "" {
					carrier = query.Get("carrier")
				}
				if query.Get("transport") != "" {
					transport = query.Get("transport")
				}
			}
		}

		// Определяем красивое имя для интерфейса
		var hostName string = "Яндекс.Телемост"
		if carrier == "wbstream" {
			hostName = "Wildberries Stream"
		} else if carrier == "vkvideo" {
			hostName = "ВКонтакте Видео"
		} else if carrier == "jazz" {
			hostName = "СберJazz"
		}

		// Парсим room_id:key (разделяя по последнему двоеточию, чтобы room_id мог содержать двоеточия, например roomId:password для SaluteJazz)
		lastColon := strings.LastIndex(credentials, ":")
		if lastColon == -1 {
			return nil, fmt.Errorf("неверный формат olcrtc ссылки (отсутствует room_id или key)")
		}
		
		roomID := credentials[:lastColon]
		key := credentials[lastColon+1:]

		return &V2RayServer{
			Title:     name,
			Protocol:  "olcrtc",
			RoomID:    roomID,
			Key:       key,
			Carrier:   carrier,
			Transport: transport,
			Host:      hostName,
			Port:      443,
			FullLink:  cleanLine, // Чтобы Android мог передать чистую ссылку
		}, nil
	}

	return nil, fmt.Errorf("unsupported protocol")
}
