package vpncore

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"

	box "github.com/sagernet/sing-box"
	"github.com/sagernet/sing-box/option"
)

type VlessConfig struct {
	UUID      string
	Host      string
	Port      string
	SNI       string
	PublicKey string
	ShortId   string
	Flow      string
	Finger    string
	FullLink  string // Полная оригинальная ссылка со всеми параметрами
	Title     string // Название сервера, вытащенное из хештега #
}

type NaiveConfig struct {
	Username string
	Password string
	Host     string
	Port     string
	SNI      string
	Title    string
}

// Переменная для хранения запущенного движка Sing-Box
var singBoxInstance *box.Box

func ParseVlessLink(vlessLink string) (*VlessConfig, error) {
	fmt.Println("Парсим ссылку VLESS:", vlessLink)
	parsedUrl, err := url.Parse(vlessLink)
	if err != nil {
		return nil, fmt.Errorf("не удалось прочитать ссылку: %v", err)
	}

	if parsedUrl.Scheme != "vless" {
		return nil, fmt.Errorf("ошибка: поддерживаются только ссылки vless://")
	}

	uuid := parsedUrl.User.Username()
	host := parsedUrl.Hostname()
	port := parsedUrl.Port()
	queryParams := parsedUrl.Query()

	finger := queryParams.Get("fp")
	if finger == "" {
		finger = "chrome" // Дефолт, если сервер не указал отпечаток
	}

	title := parsedUrl.Fragment
	if title == "" {
		title = host // фоллбэк
	}

	config := &VlessConfig{
		UUID:      uuid,
		Host:      host,
		Port:      port,
		SNI:       queryParams.Get("sni"),
		PublicKey: queryParams.Get("pbk"),
		ShortId:   queryParams.Get("sid"),
		Flow:      queryParams.Get("flow"),
		Finger:    finger,
		FullLink:  vlessLink,
		Title:     title,
	}

	return config, nil
}

func ParseNaiveLink(naiveLink string) (*NaiveConfig, error) {
	fmt.Println("Парсим ссылку Naive:", naiveLink)
	
	// Превращаем схему в валидный URL для url.Parse (заменяем naive/naive+https на https)
	cleanLink := naiveLink
	if strings.HasPrefix(cleanLink, "naive+https://") {
		cleanLink = strings.Replace(cleanLink, "naive+https://", "https://", 1)
	} else if strings.HasPrefix(cleanLink, "naive://") {
		cleanLink = strings.Replace(cleanLink, "naive://", "https://", 1)
	}

	parsedUrl, err := url.Parse(cleanLink)
	if err != nil {
		return nil, fmt.Errorf("не удалось прочитать ссылку Naive: %v", err)
	}

	var username, password string
	if parsedUrl.User != nil {
		username = parsedUrl.User.Username()
		password, _ = parsedUrl.User.Password()
	}

	host := parsedUrl.Hostname()
	port := parsedUrl.Port()
	if port == "" {
		port = "443" // Дефолтный HTTPS порт
	}

	queryParams := parsedUrl.Query()
	sni := queryParams.Get("sni")
	if sni == "" {
		sni = host
	}

	title := parsedUrl.Fragment
	if title == "" {
		title = host
	}

	return &NaiveConfig{
		Username: username,
		Password: password,
		Host:     host,
		Port:     port,
		SNI:      sni,
		Title:    title,
	}, nil
}

// StartSingBoxEngine запускает ядро Sing-Box с VLESS Reality или NaiveProxy
func StartSingBoxEngine(link string) error {
	var rawJsonConfig string

	if strings.HasPrefix(link, "vless://") {
		config, err := ParseVlessLink(link)
		if err != nil {
			return err
		}

		var portNum int
		fmt.Sscanf(config.Port, "%d", &portNum)
		if portNum == 0 {
			portNum = 443
		}

		rawJsonConfig = fmt.Sprintf(`{
			"log": {
				"level": "debug"
			},
			"inbounds": [
				{
					"type": "socks",
					"tag": "socks-in",
					"listen": "127.0.0.1",
					"listen_port": 10808,
					"sniff": true,
					"sniff_override_destination": true
				}
			],
			"outbounds": [
				{
					"type": "vless",
					"tag": "proxy",
					"server": "%s",
					"server_port": %d,
					"uuid": "%s",
					"flow": "%s",
					"tls": {
						"enabled": true,
						"server_name": "%s",
						"utls": {
							"enabled": true,
							"fingerprint": "%s"
						},
						"reality": {
							"enabled": true,
							"public_key": "%s",
							"short_id": "%s"
						}
					}
				}
			]
		}`, config.Host, portNum, config.UUID, config.Flow, config.SNI, config.Finger, config.PublicKey, config.ShortId)

	} else if strings.HasPrefix(link, "naive://") || strings.HasPrefix(link, "naive+https://") {
		config, err := ParseNaiveLink(link)
		if err != nil {
			return err
		}

		var portNum int
		fmt.Sscanf(config.Port, "%d", &portNum)
		if portNum == 0 {
			portNum = 443
		}

		rawJsonConfig = fmt.Sprintf(`{
			"log": {
				"level": "debug"
			},
			"inbounds": [
				{
					"type": "socks",
					"tag": "socks-in",
					"listen": "127.0.0.1",
					"listen_port": 10808,
					"sniff": true,
					"sniff_override_destination": true
				}
			],
			"outbounds": [
				{
					"type": "naive",
					"tag": "proxy",
					"server": "%s",
					"server_port": %d,
					"username": "%s",
					"password": "%s",
					"tls": {
						"enabled": true,
						"server_name": "%s"
					}
				}
			]
		}`, config.Host, portNum, config.Username, config.Password, config.SNI)
	} else {
		return fmt.Errorf("неподдерживаемый тип ссылки для Sing-Box")
	}

	return runSingBox(rawJsonConfig)
}

// StartSingBoxWithLocalSocks запускает Sing-Box в режиме SOCKS-to-SOCKS для OlcRTC
func StartSingBoxWithLocalSocks(outboundSocksPort int) error {
	rawJsonConfig := fmt.Sprintf(`{
		"log": {
			"level": "debug"
		},
		"inbounds": [
			{
				"type": "socks",
				"tag": "socks-in",
				"listen": "127.0.0.1",
				"listen_port": 10808,
				"sniff": true,
				"sniff_override_destination": true
			}
		],
		"outbounds": [
			{
				"type": "socks",
				"tag": "socks-out",
				"server": "127.0.0.1",
				"server_port": %d
			}
		]
	}`, outboundSocksPort)

	return runSingBox(rawJsonConfig)
}

func runSingBox(rawJsonConfig string) error {
	var options option.Options
	err := json.Unmarshal([]byte(rawJsonConfig), &options)
	if err != nil {
		return fmt.Errorf("ошибка парсинга конфига Sing-Box: %w", err)
	}

	instance, err := box.New(box.Options{
		Options: options,
	})
	if err != nil {
		return fmt.Errorf("ошибка инициализации ядра Sing-Box: %w", err)
	}

	singBoxInstance = instance
	err = singBoxInstance.Start()
	if err != nil {
		return fmt.Errorf("ошибка старта ядра Sing-Box: %w", err)
	}

	fmt.Println("===== ЯДРО SING-BOX УСПЕШНО ЗАПУЩЕНО! =====")
	return nil
}

func StopSingBoxEngine() {
	if singBoxInstance != nil {
		singBoxInstance.Close()
		singBoxInstance = nil
		fmt.Println("Sing-Box остановлен.")
	}
}
