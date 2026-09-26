# sing-box-config-template
**Server:** 
 - hy2 template
 - Tailscale DERP 
 - ACME证书（域名在CF配置示例）

**Client** hy2 template
 1. sing-box 1.14
     -  DNS race
     -  国内realip，国外Fake ip
     -  ipv4&v6(自动判断v6规则，没有V6自动拦截）
     -  Ad block（广告拦截）
     -  Webrtc leak protect（webrtc拦截防止ip泄漏）
     -  tailscale ( if you don't need , delect the DNS/route rule / endpoint config)
     -  Sing-box api & clash api
   
 2. sing-box 1.15 
     -  DNS race
     -  国内realip，国外Fake ip
     -  ipv4&v6(自动判断v6规则，没有V6自动拦截）
     -  Ad block（广告拦截）
     -  Webrtc leak protect（webrtc拦截防止ip泄漏）
     -  tailscale(on demand)
     -  Sing-box api & clash api
   
 3. sing-box 1.15 bridge ( for mac/linux/root android) iPhone support only when jail break
     -  DNS race
     -  国内realip，国外Fake ip
     -  ipv4&v6(自动判断v6规则，没有V6自动拦截）
     -  Ad block（广告拦截）
     -  Webrtc leak protect（webrtc拦截防止ip泄漏）
     -  tailscale (on demand)
     -  Sing-box api & clash api
   
 4. sing-box 1.15 mac mini side router 
     -  DNS race
     -  国内realip，国外Fake ip
     -  ipv4&v6(自动判断v6规则，没有V6自动拦截）
     -  Ad block（广告拦截）
     -  Webrtc leak protect（webrtc拦截防止ip泄漏）
     -  tailscale (on demand)
     -  Bridge on pre-match
     -  Sing-box api & clash api
