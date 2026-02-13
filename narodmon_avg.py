"""
Вызов: pyscript.narodmon_update
"""

import requests
import datetime
import json

# Кэш для типов
sensor_types_cache = {}
last_types_update = 0

@service
def narodmon_update(sensor_type=None):
    """Обновить данные. Без параметра - обновляет все типы одним запросом"""
    
    log.info("=" * 50)
    log.info("NARODMON UPDATE STARTED")
    
    # Получаем ключи
    api_key = pyscript.config.get("narodmon", {}).get("api_key")
    uuid = pyscript.config.get("narodmon", {}).get("uuid", "")
    
    if not api_key:
        log.error("No API key")
        return
    
    # Координаты
    try:
        zone_attrs = state.getattr("zone.home")
        lat = float(zone_attrs['latitude'])
        lon = float(zone_attrs['longitude'])
    except Exception as e:
        log.error(f"Error getting coordinates: {e}")
        exit()

    log.info(f"📍 Location: {lat}, {lon}")
    log.info(f"🔑 API Key: {api_key[:4]}...{api_key[-4:]}")
    log.info(f"🆔 UUID: {uuid[:8] if uuid else 'not set'}")
    
    # Получаем типы сенсоров
    types = get_sensor_types(api_key, uuid)
    
    # Определяем какие типы запрашивать
    if sensor_type:
        # Один конкретный тип
        types_str = str(sensor_type)
        log.info(f"📡 Updating single type: {sensor_type}")
    else:
        # ВСЕ ТИПЫ ОДНИМ ЗАПРОСОМ (через запятую)
        all_types = list(types.keys())
        type_list = []
        for t in all_types:
            type_list.append(str(t))
        types_str = ",".join(type_list)
        
        log.info(f"📡 Updating ALL types in one request: {len(all_types)} types")
    
    # ОДИН ЗАПРОС НА ВСЕ ТИПЫ
    try:
        params = {
            "lat": lat,
            "lon": lon,
            "radius": 10,
            "types": types_str,  # все типы через запятую
            "uuid": uuid,
            "lang": "ru",
            "api_key": api_key
        }
        
        response = task.executor(
            requests.get,
            "http://api.narodmon.ru/sensorsNearby",
            params=params,
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            devices = data.get('devices', [])
            log.info(f"📡 Found {len(devices)} devices")
            
            # Сохраняем сырой ответ
            state.set(
                "sensor.narodmon_response",
                value=len(devices),
                new_attributes={
                    "raw_response": json.dumps(data, ensure_ascii=False),
                    "devices_count": len(devices),
                    "types_requested": types_str,
                    "latitude": lat,
                    "longitude": lon,
                    "last_update": datetime.datetime.utcnow().isoformat()
                }
            )
            
            # ОБРАБАТЫВАЕМ ВСЕ ТИПЫ ИЗ ОДНОГО ОТВЕТА
            process_response(data, types)
            
        else:
            log.error(f"❌ API error: {response.status_code}")
            
    except Exception as e:
        log.error(f"❌ Error: {e}")
    
    log.info("NARODMON UPDATE COMPLETED")
    log.info("=" * 50)

def process_response(data, types):
    """Обработать ответ API и создать сенсоры для всех найденных типов"""
    
    devices = data.get('devices', [])
    
    # Группируем значения по типам сенсоров
    type_values = {}
    type_devices = {}
    
    for device in devices:
        for sensor in device.get('sensors', []):
            s_type = sensor['type']
            
            try:
                value = float(sensor['value'])
                
                if s_type not in type_values:
                    type_values[s_type] = []
                    type_devices[s_type] = []
                
                type_values[s_type].append(value)
                if device.get('name') not in type_devices[s_type]:
                    type_devices[s_type].append(device.get('name', 'Unknown'))
                    
            except (ValueError, TypeError):
                continue
    
    # Создаем сенсоры для каждого типа
    for s_type, values in type_values.items():
        if not values:
            continue
            
        # Среднее значение
        avg_value = sum(values) / len(values)
        
        # Информация о типе
        type_info = types.get(s_type, {
            "name": f"Type {s_type}",
            "unit": "",
            "icon": "mdi:sensor"
        })
        
        # Английское имя для entity_id
        eng_names = {
            1: "temperature",
            2: "humidity",
            3: "pressure",
            4: "wind_speed",
            5: "wind_direction",
            11: "illuminance",
            21: "dew_point",
            22: "dust",
            24: "water_temperature",
            25: "soil_temperature"
        }
        
        eng_name = eng_names.get(s_type, f"type_{s_type}")
        sensor_id = f"narodmon_{eng_name}"
        
        # Создаем сенсор
        state.set(
            f"sensor.{sensor_id}",
            value=round(avg_value, 1),
            new_attributes={
                "avg": round(avg_value, 2),
                "count": len(values),
                "devices": len(set(type_devices[s_type])),
                "type_id": s_type,
                "type_name": type_info['name'],
                "unit": type_info['unit'],
                "icon": type_info['icon'],
                "last_update": datetime.datetime.utcnow().isoformat(),
                "friendly_name": f"Narodmon {type_info['name']}"
            }
        )
        
        log.info(f"  ✅ {type_info['name']}: {avg_value:.1f}{type_info['unit']} ({len(values)} sensors)")

def get_sensor_types(api_key, uuid):
    """Получить список всех типов сенсоров с кэшированием"""
    global sensor_types_cache, last_types_update
    
    import time
    current_time = time.time()
    
    # Используем кэш если он свежий (24 часа)
    if sensor_types_cache and (current_time - last_types_update) < 86400:
        return sensor_types_cache
    
    try:
        params = {
            "version": "1.1",
            "platform": "6.0.1",
            "uuid": uuid,
            "lang": "ru",
            "utc": 3,
            "api_key": api_key
        }
        
        response = task.executor(
            requests.get,
            "http://api.narodmon.ru/appInit",
            params=params,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            types = {}
            
            for t in data.get('types', []):
                type_id = t['type']
                types[type_id] = {
                    'name': t['name'],
                    'unit': t['unit'],
                    'icon': get_icon_for_type(type_id)
                }
            
            sensor_types_cache = types
            last_types_update = current_time
            log.info(f"✅ Loaded {len(types)} sensor types from API")
            
            # Сохраняем список типов в сенсор
            state.set(
                "sensor.narodmon_types",
                value=len(types),
                new_attributes={
                    "types": json.dumps(types, ensure_ascii=False),
                    "count": len(types),
                    "last_update": datetime.datetime.utcnow().isoformat(),
                    "friendly_name": "Narodmon Sensor Types"
                }
            )
            
            return types
        else:
            log.warning(f"Failed to load types: {response.status_code}")
            return get_default_types()
            
    except Exception as e:
        log.warning(f"Error loading types: {e}")
        return get_default_types()

def get_default_types():
    """Типы по умолчанию на случай ошибки API"""
    return {
        1: {"name": "Температура", "unit": "°C", "icon": "mdi:thermometer"},
        2: {"name": "Влажность", "unit": "%", "icon": "mdi:water-percent"},
        3: {"name": "Давление", "unit": "mmHg", "icon": "mdi:gauge"},
        4: {"name": "Скорость ветра", "unit": "m/s", "icon": "mdi:weather-windy"},
        5: {"name": "Направление ветра", "unit": "°", "icon": "mdi:compass"},
        11: {"name": "Освещенность", "unit": "Lx", "icon": "mdi:brightness-6"},
        21: {"name": "Точка росы", "unit": "°C", "icon": "mdi:thermometer-water"},
        22: {"name": "Запыленность", "unit": "µg/m³", "icon": "mdi:smoke"},
        24: {"name": "Температура воды", "unit": "°C", "icon": "mdi:waves"},
        25: {"name": "Температура почвы", "unit": "°C", "icon": "mdi:leaf"}
    }

def get_icon_for_type(type_id):
    """Иконка для типа сенсора"""
    icons = {
        1: "mdi:thermometer",        # температура
        2: "mdi:water-percent",      # влажность
        3: "mdi:gauge",              # давление
        4: "mdi:weather-windy",      # скорость ветра
        5: "mdi:compass",            # направление ветра
        9: "mdi:weather-rainy",      # осадки
        11: "mdi:brightness-6",      # освещенность
        21: "mdi:thermometer-water", # точка росы
        22: "mdi:smoke",             # запыленность
        24: "mdi:waves",             # температура воды
        25: "mdi:leaf",              # температура почвы
    }
    return icons.get(type_id, "mdi:sensor")

@service
def narodmon_update_single(sensor_type):
    """Обновить один конкретный тип"""
    narodmon_update(sensor_type)

# Автоматическое обновление при старте
@time_trigger("startup")
def narodmon_startup():
    log.info("🚀 Narodmon script loaded")
    task.sleep(30)
    narodmon_update()

# Плановое обновление раз в 30 минут
@time_trigger("periodic(0, 30)")
def narodmon_scheduled():
    narodmon_update()


@service
def narodmon_remove_all():
    """Удалить все сенсоры Narodmon"""
    
    log.info("=" * 50)
    log.info("🗑️ REMOVING ALL NARODMON SENSORS")
    
    # Получаем все состояния
    all_states = state.names()
    removed_count = 0
    
    for entity_id in all_states:
        if entity_id.startswith("sensor.narodmon_") or entity_id.startswith("sensor.test_") or entity_id.startswith("input_text.narodmon_"):
            try:
                # Удаляем состояние
                state.delete(entity_id)
                log.info(f"  ✅ Removed: {entity_id}")
                removed_count += 1
                task.sleep(0.1)  # небольшая пауза
            except Exception as e:
                log.error(f"  ❌ Failed to remove {entity_id}: {e}")
    
    log.info(f"✅ Removed {removed_count} entities")
    log.info("=" * 50)