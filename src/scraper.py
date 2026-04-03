import os
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

# URL de búsqueda: compra en Tres Cantos, hasta 500.000€, mínimo 1 habitación
IDEALISTA_URL = (
    "https://www.idealista.com/venta-viviendas/tres-cantos-madrid/"
    "?ordenado-por=fecha-publicacion-desc"
)

MAX_PRECIO = 500_000
MIN_HABITACIONES = 1

# Fichero donde guardamos los anuncios ya notificados (se commitea al repo)
SEEN_FILE = "seen_listings.json"

# ─── CREDENCIALES (desde GitHub Secrets / variables de entorno) ───────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ─── HEADERS para imitar un navegador real ────────────────────────────────────

HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.es/",
        "Connection": "keep-alive",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.es/",
        "Connection": "keep-alive",
    },
]


# ─── FUNCIONES ────────────────────────────────────────────────────────────────

def cargar_vistos():
    """Carga los IDs de anuncios ya notificados desde el fichero JSON."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def guardar_vistos(vistos):
    """Guarda los IDs de anuncios ya notificados en el fichero JSON."""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(vistos), f)


def enviar_telegram(mensaje):
    """Envía un mensaje al bot de Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Faltan credenciales de Telegram en las variables de entorno.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
        return False


def parsear_precio(texto_precio):
    """Convierte '320.000 €' a 320000 (int)."""
    try:
        limpio = texto_precio.replace("€", "").replace(".", "").replace(",", "").strip()
        return int(limpio)
    except Exception:
        return None


def parsear_habitaciones(texto):
    """Extrae el número de habitaciones de un texto como '3 hab.'"""
    try:
        return int(texto.strip().split()[0])
    except Exception:
        return 0


def scrape_idealista():
    """Hace scraping de la página de resultados y devuelve lista de anuncios."""
    headers = random.choice(HEADERS_LIST)
    time.sleep(random.uniform(3, 7))  # Delay para no levantar sospechas

    try:
        response = requests.get(IDEALISTA_URL, headers=headers, timeout=15)
    except Exception as e:
        print(f"Error al conectar con Idealista: {e}")
        return []

    if response.status_code != 200:
        print(f"Idealista devolvió status {response.status_code}. Posible bloqueo.")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    anuncios_raw = soup.select("article.item")

    if not anuncios_raw:
        print("No se encontraron anuncios. El HTML puede haber cambiado o hay bloqueo.")
        return []

    anuncios = []
    for item in anuncios_raw:
        try:
            # ID único del anuncio
            anuncio_id = item.get("data-adid") or item.get("data-element-id")
            if not anuncio_id:
                continue

            # Título y URL
            link_tag = item.select_one("a.item-link")
            titulo = link_tag.get("title", "Sin título").strip() if link_tag else "Sin título"
            url = "https://www.idealista.com" + link_tag["href"] if link_tag else ""

            # Precio
            precio_tag = item.select_one(".item-price")
            precio_texto = precio_tag.get_text(strip=True) if precio_tag else ""
            precio = parsear_precio(precio_texto)

            # Detalles: habitaciones, m², planta
            detalles = item.select(".item-detail")
            habitaciones = 0
            metros = ""
            planta = ""

            for d in detalles:
                texto = d.get_text(strip=True).lower()
                if "hab" in texto:
                    habitaciones = parsear_habitaciones(texto)
                elif "m²" in texto:
                    metros = d.get_text(strip=True)
                elif "planta" in texto or "bajo" in texto or "ático" in texto:
                    planta = d.get_text(strip=True)

            anuncios.append({
                "id": anuncio_id,
                "titulo": titulo,
                "url": url,
                "precio": precio,
                "precio_texto": precio_texto,
                "habitaciones": habitaciones,
                "metros": metros,
                "planta": planta,
            })

        except Exception as e:
            print(f"Error parseando anuncio: {e}")
            continue

    return anuncios


def filtrar_anuncios(anuncios, vistos):
    """Filtra por precio, habitaciones y que no hayan sido notificados ya."""
    nuevos = []
    for a in anuncios:
        if a["id"] in vistos:
            continue
        if a["precio"] is not None and a["precio"] > MAX_PRECIO:
            continue
        if a["habitaciones"] < MIN_HABITACIONES:
            continue
        nuevos.append(a)
    return nuevos


def formatear_mensaje(anuncio):
    """Formatea el mensaje de Telegram para un anuncio."""
    lineas = [
        f"🏠 <b>{anuncio['titulo']}</b>",
        f"💶 <b>{anuncio['precio_texto']}</b>",
    ]
    if anuncio["habitaciones"]:
        lineas.append(f"🛏 {anuncio['habitaciones']} habitación(es)")
    if anuncio["metros"]:
        lineas.append(f"📐 {anuncio['metros']}")
    if anuncio["planta"]:
        lineas.append(f"🏢 {anuncio['planta']}")
    if anuncio["url"]:
        lineas.append(f"\n🔗 <a href='{anuncio['url']}'>Ver anuncio</a>")
    return "\n".join(lineas)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando scraper...")

    vistos = cargar_vistos()
    print(f"Anuncios ya vistos: {len(vistos)}")

    anuncios = scrape_idealista()
    print(f"Anuncios encontrados en Idealista: {len(anuncios)}")

    nuevos = filtrar_anuncios(anuncios, vistos)
    print(f"Anuncios nuevos que cumplen filtros: {len(nuevos)}")

    if not nuevos:
        print("Sin novedades. Nada que notificar.")
    else:
        for anuncio in nuevos:
            mensaje = formatear_mensaje(anuncio)
            ok = enviar_telegram(mensaje)
            estado = "✅ Enviado" if ok else "❌ Error al enviar"
            print(f"{estado}: {anuncio['titulo']} — {anuncio['precio_texto']}")
            vistos.add(anuncio["id"])
            time.sleep(1)  # Pequeña pausa entre mensajes

    guardar_vistos(vistos)
    print("Scraper finalizado.")


if __name__ == "__main__":
    main()
