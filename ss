[0;1;32m●[0m dnsmasq.service - dnsmasq - A lightweight DHCP and caching DNS server
     Loaded: loaded (]8;;file://navneeth-arun04-Dell-G16-7630/usr/lib/systemd/system/dnsmasq.service\/usr/lib/systemd/system/dnsmasq.service]8;;\; [0;1;32menabled[0m; preset: [0;1;32menabled[0m)
     Active: [0;1;32mactive (running)[0m since Mon 2025-11-03 21:48:51 IST; 1min 29s ago
 Invocation: 44cc610850dd4ad0a0ee0da64a2ee1a3
       Docs: ]8;;man:dnsmasq(8)\man:dnsmasq(8)]8;;\
    Process: 25381 ExecStartPre=/usr/share/dnsmasq/systemd-helper checkconfig (code=exited, status=0/SUCCESS)
    Process: 25388 ExecStart=/usr/share/dnsmasq/systemd-helper exec (code=exited, status=0/SUCCESS)
    Process: 25395 ExecStartPost=/usr/share/dnsmasq/systemd-helper start-resolvconf (code=exited, status=0/SUCCESS)
   Main PID: 25394 (dnsmasq)
      Tasks: 1[0;38;5;245m (limit: 37312)[0m
     Memory: 1.2M (peak: 5.3M)
        CPU: 75ms
     CGroup: /system.slice/dnsmasq.service
             └─[0;38;5;245m25394 /usr/sbin/dnsmasq -x /run/dnsmasq/dnsmasq.pid -u dnsmasq -r /run/dnsmasq/resolv.conf -7 /etc/dnsmasq.d,.dpkg-dist,.dpkg-old,.dpkg-new --local-service --trust-anchor=.,20326,8,2,E06D44B80B8F1D39A95C0B0D7C65D08458E880409BBC683457104237C7F8EC8D --trust-anchor=.,38696,8,2,683D2D0ACB8C9B712A1948B27F741219298D0A450D612C483AF444A4C0FB2B16[0m

Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq[25394]: compile time options: IPv6 GNU-getopt DBus no-UBus i18n IDN2 DHCP DHCPv6 no-Lua TFTP conntrack ipset nftset auth DNSSEC loop-detect inotify dumpfile
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq[25394]: [0;1;38:5:185m[0;1;39m[0;1;38:5:185mwarning: interface enp3s0 does not currently exist[0m
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq[25394]: [0;1;38:5:185m[0;1;39m[0;1;38:5:185mwarning: interface enp3s0 does not currently exist[0m
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq[25394]: [0;1;38:5:185m[0;1;39m[0;1;38:5:185mwarning: ignoring resolv-file flag because no-resolv is set[0m
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq-dhcp[25394]: DHCP, IP range 192.168.0.100 -- 192.168.0.200, lease time 12h
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq[25394]: using nameserver 192.168.0.10#53
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 dnsmasq[25394]: read /etc/hosts - 8 names
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 systemd[1]: Started dnsmasq.service - dnsmasq - A lightweight DHCP and caching DNS server.
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 resolvconf[25402]: Dropped protocol specifier '.dnsmasq' from 'lo.dnsmasq'. Using 'lo' (ifindex=1).
Nov 03 21:48:51 navneeth-arun04-Dell-G16-7630 resolvconf[25402]: [0;1;31m[0;1;39m[0;1;31mFailed to set DNS configuration: Unit dbus-org.freedesktop.network1.service not found.[0m
