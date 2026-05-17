package vpncore

import (
	"fmt"
	"net/url"
	"strings"

	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/infra/conf/serial"
	_ "github.com/xtls/xray-core/main/distro/all" // Важнейший импорт: загружает все протоколы (VLESS, REALITY, TUN)
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
	FullLink  string // Полная оригинальная ссылка со всеми параметрами (чтобы Kotlin не собирал её сам)
	Title     string // Название сервера, вытащенное из хештега #
}

// Переменная для хранения запущенного движка, чтобы мы могли его остановить
var xrayInstance *core.Instance

func ParseVlessLink(vlessLink string) (*VlessConfig, error) {
	fmt.Println("Парсим ссылку:", vlessLink)
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
		finger = "chrome" // Дефолт, если сервер не указал отпечаток (иначе Xray крашится с пустой строкой)
	}

	title := parsedUrl.Fragment
	if title == "" {
		title = host // фоллбэк: если имени нет, ставим IP/домен сервера
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

// Эта функция теперь РЕАЛЬНО запускает движок Xray на телефоне!
func StartXrayEngine(vlessLink string) error {
	config, err := ParseVlessLink(vlessLink)
	if err != nil {
		return err
	}

	// 1. Собираем "конфиг" для Xray в виде JSON строк.
	// Здесь мы создаем базовую архитектуру: входящий трафик (SOCKS локально) -> исходящий трафик (VLESS Reality).
	// В Happ/v2raytun обычно генерируют такой JSON и запускают ядро.

	sockoptStr := ""
	fragmentOutbound := ""

	if EnableDPIFragmentation {
		fmt.Println("ВКЛЮЧАЕМ НАТИВНЫЙ ФРАГМЕНТАТОР XRAY!")
		sockoptStr = `,
				"sockopt": {
					"dialerProxy": "fragment-out"
				}`

		fragmentOutbound = `,
		{
			"protocol": "freedom",
			"tag": "fragment-out",
			"settings": {
				"fragment": {
					"packets": "tlshello",
					"length": "100-200",
					"interval": "10-20"
				}
			},
			"streamSettings": {
				"sockopt": {
					"tcpNoDelay": true
				}
			}
		}`
	}

	rawJsonConfig := fmt.Sprintf(`{
		"log": {
			"loglevel": "debug"
		},
		"inbounds": [{
			"port": 10808,
			"listen": "127.0.0.1",
			"protocol": "socks",
			"settings": {
				"auth": "noauth",
				"udp": true
			}
		}],
		"outbounds": [{
			"protocol": "vless",
			"settings": {
				"vnext": [{
					"address": "%s",
					"port": %s,
					"users": [{"id": "%s", "flow": "%s", "encryption": "none"}]
				}]
			},
			"streamSettings": {
				"network": "tcp",
				"security": "reality",
				"realitySettings": {
					"serverName": "%s",
					"publicKey": "%s",
					"shortId": "%s",
					"fingerprint": "%s"
				}%s
			}
		}%s]
	}`, config.Host, config.Port, config.UUID, config.Flow, config.SNI, config.PublicKey, config.ShortId, config.Finger, sockoptStr, fragmentOutbound)

	// 2. Превращаем наш JSON-текст в формат, который понимает `Xray-core`
	pbConfig, err := serial.DecodeJSONConfig(strings.NewReader(rawJsonConfig))
	if err != nil {
		return fmt.Errorf("ошибка при чтении конфига Xray: %w", err)
	}
	
	coreConfig, err := pbConfig.Build()
	if err != nil {
		return fmt.Errorf("ошибка при сборке конфига Xray: %w", err)
	}

	// 3. Создаем инстанс Ядра!
	instance, err := core.New(coreConfig)
	if err != nil {
		return fmt.Errorf("ошибка при запуске ядра Xray: %w", err)
	}

	// 4. Сохраняем и запускаем
	xrayInstance = instance
	if err := xrayInstance.Start(); err != nil {
		return fmt.Errorf("ядро Xray крашнулось при запуске: %w", err)
	}

	fmt.Println("===== XRAY-CORE ЗАПУЩЕН! ВЕСЬ ТРАФИК ИДЕТ ЧЕРЕЗ VLESS-REALITY! =====")
	return nil
}

// StopXrayEngine плавно останавливает ядро
func StopXrayEngine() {
	if xrayInstance != nil { // Исправлено на nil!
		xrayInstance.Close()
		xrayInstance = nil
		fmt.Println("Xray-core остановлен.")
	}
}
