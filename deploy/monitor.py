#!/usr/bin/env python3
"""Server yukini kuzatadi: jonli darsda nechta odam bor va server qancha band.

Serverda, deploy papkasida ishga tushiriladi (qo'shimcha kutubxona kerak emas):

    python3 monitor.py            # har 5 soniyada bir qator
    python3 monitor.py 2          # har 2 soniyada

Ctrl+C bosilganda eng yuqori ko'rsatkichlar chiqadi. Hamma o'lchovlar yonidagi CSV faylga ham yoziladi.

Ustunlar:
    odam / xona   LiveKit'dagi ishtirokchilar va ochiq darslar soni
    CPU           barcha yadrolar bo'yicha o'rtacha bandlik (100% = hammasi to'la)
    load          1 daqiqalik yuklama (yadrolar sonidan oshsa — server ulgurmayapti)
    RAM           band xotira
    kirish/chiqish  tarmoq tezligi, Mbit/s (chiqish — serverdan ishtirokchilarga ketayotgan video)
    livekit / api / media   har bir konteynerning CPU sarfi (100% = bitta yadro)
"""

import base64
import csv
import hashlib
import hmac
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
CONTAINERS = ("livekit", "api", "media")


def read_env(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and not key.strip().startswith("#"):
                values[key.strip()] = value.strip()
    return values


ENV = {**read_env(HERE / ".env"), **os.environ}
# Sinov uchun boshqa manzilni ko'rsatish mumkin; odatda Caddy orqali (https://DOMAIN) so'raladi
LIVEKIT_URL = ENV.get("LIVEKIT_HTTP_URL") or f"https://{ENV.get('DOMAIN', 'localhost')}"


def livekit_token() -> str:
    """LiveKit API uchun qisqa muddatli ruxsat (HS256 JWT) — faqat xonalar ro'yxatini ko'rishga."""
    def encode(data: dict) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).rstrip(b"=")

    now = int(time.time())
    body = encode({"alg": "HS256", "typ": "JWT"}) + b"." + encode(
        {"iss": ENV["LIVEKIT_API_KEY"], "nbf": now - 10, "exp": now + 60, "video": {"roomList": True}}
    )
    signature = hmac.new(ENV["LIVEKIT_API_SECRET"].encode(), body, hashlib.sha256).digest()
    return (body + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def livekit_rooms() -> tuple:
    """(ishtirokchilar, xonalar). LiveKit javob bermasa (None, None)."""
    request = urllib.request.Request(
        f"{LIVEKIT_URL}/twirp/livekit.RoomService/ListRooms", data=b"{}",
        headers={"Authorization": f"Bearer {livekit_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=4, context=ssl.create_default_context()) as response:
            rooms = json.load(response).get("rooms", [])
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
        return None, None
    # maydon nomi LiveKit versiyasiga qarab ikki xil yozilishi mumkin
    return sum(int(room.get("num_participants", room.get("numParticipants", 0))) for room in rooms), len(rooms)


def cpu_times() -> tuple:
    fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + fields[4]  # idle + iowait
    return sum(fields), idle


def memory_used_mb() -> float:
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":")
        info[key] = int(value.split()[0])
    return (info["MemTotal"] - info["MemAvailable"]) / 1024


def default_interface() -> str:
    for line in Path("/proc/net/route").read_text().splitlines()[1:]:
        fields = line.split()
        if fields[1] == "00000000":
            return fields[0]
    return "eth0"


def network_bytes(interface: str) -> tuple:
    for line in Path("/proc/net/dev").read_text().splitlines():
        name, separator, rest = line.partition(":")
        if separator and name.strip() == interface:
            fields = rest.split()
            return int(fields[0]), int(fields[8])
    return 0, 0


container_cpu: dict = {}


def watch_containers() -> None:
    """`docker stats` sekin (2 soniyacha), shuning uchun alohida oqimda aylanadi."""
    while True:
        try:
            output = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}}"],
                capture_output=True, text=True, timeout=20,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return  # docker yo'q yoki ruxsat yo'q — konteyner ustunlari bo'sh qoladi
        for line in output.splitlines():
            name, _, percent = line.partition(" ")
            for container in CONTAINERS:
                if f"-{container}-" in name:
                    container_cpu[container] = float(percent.rstrip("%") or 0)
        time.sleep(1)


def show(value, pattern: str) -> str:
    return "-" if value is None else pattern.format(value)


def main() -> None:
    interface = default_interface()
    cores = os.cpu_count() or 1
    log_path = HERE / f"monitor-{datetime.now():%Y%m%d-%H%M%S}.csv"
    threading.Thread(target=watch_containers, daemon=True).start()

    header = ["vaqt", "odam", "xona", "cpu_%", "load1", "ram_mb", "kirish_mbit", "chiqish_mbit",
              *[f"{name}_cpu_%" for name in CONTAINERS]]
    print(f"Tarmoq: {interface} | yadrolar: {cores} | LiveKit: {LIVEKIT_URL} | jurnal: {log_path.name}")
    print(f"{'vaqt':8} {'odam':>4} {'xona':>4} {'CPU':>5} {'load':>5} {'RAM':>8} {'kirish':>9} {'chiqish':>9}  "
          + "  ".join(f"{name:>8}" for name in CONTAINERS))

    peak = {"odam": 0, "cpu": 0.0, "load": 0.0, "ram": 0.0, "kirish": 0.0, "chiqish": 0.0}
    total_out = 0
    total, idle = cpu_times()
    received, sent = network_bytes(interface)
    moment = time.monotonic()
    try:
        with log_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(header)
            while True:
                time.sleep(INTERVAL)
                people, rooms = livekit_rooms()
                new_total, new_idle = cpu_times()
                new_received, new_sent = network_bytes(interface)
                new_moment = time.monotonic()
                seconds = new_moment - moment

                cpu = 100 * (1 - (new_idle - idle) / max(1, new_total - total))
                load = os.getloadavg()[0]
                ram = memory_used_mb()
                incoming = (new_received - received) * 8 / seconds / 1e6
                outgoing = (new_sent - sent) * 8 / seconds / 1e6
                total_out += new_sent - sent
                total, idle, received, sent, moment = new_total, new_idle, new_received, new_sent, new_moment

                containers = [container_cpu.get(name) for name in CONTAINERS]
                print(f"{datetime.now():%H:%M:%S} {show(people, '{}'):>4} {show(rooms, '{}'):>4} {cpu:4.0f}% {load:5.2f} "
                      f"{ram:6.0f}MB {incoming:7.1f}Mb {outgoing:7.1f}Mb  "
                      + "  ".join(f"{show(value, '{:.0f}%'):>8}" for value in containers), flush=True)
                writer.writerow([f"{datetime.now():%H:%M:%S}", people, rooms, f"{cpu:.1f}", f"{load:.2f}", f"{ram:.0f}",
                                 f"{incoming:.2f}", f"{outgoing:.2f}", *["" if value is None else f"{value:.1f}" for value in containers]])
                file.flush()

                peak["odam"] = max(peak["odam"], people or 0)
                peak["cpu"], peak["load"], peak["ram"] = max(peak["cpu"], cpu), max(peak["load"], load), max(peak["ram"], ram)
                peak["kirish"], peak["chiqish"] = max(peak["kirish"], incoming), max(peak["chiqish"], outgoing)
    except KeyboardInterrupt:
        pass
    print("\n--- eng yuqori ko'rsatkichlar ---")
    print(f"ishtirokchilar: {peak['odam']}")
    print(f"CPU: {peak['cpu']:.0f}%   load: {peak['load']:.2f} ({cores} yadro)   RAM: {peak['ram']:.0f} MB")
    print(f"tarmoq: kirish {peak['kirish']:.1f} Mbit/s, chiqish {peak['chiqish']:.1f} Mbit/s")
    print(f"jami yuborilgan: {total_out / 1e9:.2f} GB")
    print(f"jurnal: {log_path}")


if __name__ == "__main__":
    main()
