package main

import (
	"fmt"
	"github.com/xtls/xray-core/core"
	_ "github.com/xtls/xray-core/main/distro/all"
	"github.com/xtls/xray-core/infra/conf/serial"
	"strings"
	"v2raytun-core/vpncore"
)

func main() {
	link := "vless://028ad8f8-b796-45c1-b5a0-d887177d278a@87.120.187.242:443?type=tcp&security=reality&sni=node-4db141.binngo.online&pbk=85vrNudcU-SoOoyHiHrhL695cr6h9d-Es1Yx-v3HL34&sid=1bd828b2&flow=xtls-rprx-vision"
	configArgs, _ := vpncore.ParseVlessLink(link)

	configStr := fmt.Sprintf(`{
		"log": { "loglevel": "debug" },
		"inbounds": [{
			"port": 10808,
			"listen": "127.0.0.1",
			"protocol": "socks",
			"settings": { "auth": "noauth", "udp": true }
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
				}
			}
		}]
	}`, configArgs.Host, configArgs.Port, configArgs.UUID, configArgs.Flow, configArgs.SNI, configArgs.PublicKey, configArgs.ShortId, configArgs.Finger)
	
	pbConfig, err := serial.DecodeJSONConfig(strings.NewReader(configStr))
	if err != nil {
		fmt.Println("Detailed Parse Error:", err)
		return
	}
	config, err := pbConfig.Build()
	if err != nil {
		fmt.Println("Error building:", err)
		return
	}
	_, err = core.New(config)
	if err != nil {
		fmt.Println("Error starting:", err)
		return
	}
	fmt.Println("SUCCESS, Xray core loaded the JSON!")
}
