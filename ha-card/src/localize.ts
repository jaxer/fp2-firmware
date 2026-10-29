import type { CardConfig, HomeAssistant } from "./types.ts";

/** A deliberately small UI catalog. Device/entity/action identifiers are never translated. */
export const russian = {
  Title: "Название",
  "FP2": "FP2",
  "FP2 radar": "Радар FP2",
  "The card uses your current Home Assistant session. No token or external server is needed.":
    "Карточка использует текущий сеанс Home Assistant. Токен и внешний сервер не нужны.",
  "Connection · advanced options": "Подключение · дополнительные параметры",
  "Discard the unsaved draft?": "Отменить несохранённый черновик?",
  "Not read": "Не прочитано",
  "Not configured": "Не настроена",
  "No fresh data": "Нет свежих данных",
  Presence: "Присутствие",
  Clear: "Очистить",
  Unoccupied: "Свободно",
  Unknown: "Неизвестно",
  Draft: "Черновик",
  "Presence map": "Карта присутствия",
  Rectangle: "Прямоугольник",
  Brush: "Кисть",
  Eraser: "Ластик",
  "Radar coordinate grid · not metres": "Координатная сетка радара · не метры",
  "Radar map: 16 columns, 20 rows": "Карта радара: 16 столбцов, 20 строк",
  "SENSOR · c8 / r0": "ДАТЧИК · c8 / r0",
  "Radar target": "Цель радара",
  "Colour — zone · outline — presence": "Цвет — область · контур — присутствие",
  "Yellow — local draft": "Жёлтый — локальный черновик",
  "Sensor unavailable or data stale": "Датчик недоступен или данные устарели",
  "Area clear · waiting for movement":
    "Прихожая свободна · ожидаем движение",
  "No fresh target report": "Нет свежего отчёта о целях",
  "Target data": "Данные целей",
  "Live report": "Живой отчёт",
  "No fresh targets": "Нет свежих целей",
  "not received yet": "ещё не получен",
  "Coordinate a · raw": "Координата a · raw",
  "Coordinate b · raw": "Координата b · raw",
  "u16 · bytes 5–6": "u16 · байты 5–6",
  "Speed · raw": "Скорость · raw",
  "SNR · code": "SNR · код",
  "Status · byte 11": "Статус · байт 11",
  "Posture · code": "Поза · код",
  "255 · no value": "255 · нет значения",
  "Radar zone": "Область радара",
  "0 · no match": "0 · нет совпадения",
  "Record · 14 bytes": "Запись · 14 байт",
  "The device reported no targets.": "Устройство сообщило об отсутствии целей.",
  "Waiting for an actual radar report.": "Ожидаем реальный отчёт радара.",
  "Sensor unavailable or data stale.": "Датчик недоступен или данные устарели.",
  "Room clear.": "Помещение свободно.",
  "The last report is stale.": "Последний отчёт устарел.",
  "Waiting for fresh targets.": "Ожидаем свежие цели.",
  "Values hidden.": "Значения скрыты.",
  "Byte offsets start at 0 within each target record. Field meanings are only partly understood. SNR is a scaled code, not dB or confidence; posture is code 1/2 without confirmed posture names; code 2 is also the default (255 means no value with a nonzero status). Zone is the radar classifier’s first match, not a geometry check against this page. Speed uses internal units ×100; the physical scale is unconfirmed. These fields are not confidence estimates.":
    "Смещения байтов — от 0 внутри записи цели. Значение полей исследовано частично. SNR — масштабированный код, не дБ и не уверенность; поза — код 1/2 без названий положений; код 2 также используется по умолчанию (255 — нет значения при ненулевом статусе). Область — первое совпадение классификатора радара, не проверка геометрии этой страницы. Скорость дана во внутренних единицах ×100; физический масштаб не подтверждён. Эти поля не являются оценкой уверенности.",
  "Read from radar": "Прочитано с радара",
  "Saved observation": "Сохранённое наблюдение",
  "Read the configuration first or create a zone on the map.":
    "Сначала прочитайте конфигурацию или создайте область на карте.",
  Read: "Прочитать",
  "Edit geometry": "Изменить геометрию",
  "Create zone": "Создать область",
  "Name in Home Assistant": "Название в Home Assistant",
  "Zone settings": "Параметры области",
  "Device codes. Physical type names are unconfirmed.":
    "Коды устройства. Названия физических типов не подтверждены.",
  "Zone sensitivity": "Чувствительность области",
  "Tracker history window limit: 1 → 200, 2 → 400, 3 → 2000 internal cycles, not seconds. A longer window may retain older target evidence. This is part of the algorithm, not a confirmed “low → high sensitivity” scale. Global sensitivity works differently.":
    "Предел одного окна истории трекера: 1 → 200, 2 → 400, 3 → 2000 внутренних циклов, не секунд. Более длинное окно может сохранять старые подтверждения цели. Это часть алгоритма, а не доказанная шкала «низкая → высокая чувствительность». Глобальная чувствительность работает иначе.",
  "Type code": "Код типа",
  "Confirm deletion": "Подтвердить удаление",
  Cancel: "Отмена",
  "Delete zone…": "Удалить область…",
  "Write the zone setting and verify by reading it back?":
    "Записать параметр области и проверить чтением?",
  "Local draft": "Локальный черновик",
  "The device is unchanged. “Apply” writes the selected map and verifies it by reading it back. To remove a zone, use “Delete zone”.":
    "Устройство не изменено. «Применить» записывает выбранную карту и проверяет ответ чтением. Для удаления области используйте «Удалить область».",
  "↶ Undo": "↶ Назад",
  "↷ Redo": "↷ Вперёд",
  Discard: "Отменить",
  Apply: "Применить",
  "Special maps": "Служебные карты",
  "Select a map, then edit a local draft. Only “Apply” writes it to the device.":
    "Выберите карту, затем редактируйте локальный черновик. Запись только по кнопке «Применить».",
  "Discard the draft?": "Отменить черновик?",
  "Advanced radar settings": "Дополнительные параметры радара",
  "Numeric protocol values. Changes require confirmation and read-back verification.":
    "Числовые значения протокола. Изменение запрашивает подтверждение и проверку чтением.",
  "Individual target deletion · 0160: unavailable because the radar firmware may enter an infinite loop.":
    "Удаление отдельной цели · 0160: недоступно из-за потенциального зацикливания в прошивке радара.",
  "Background learning": "Обучение фона",
  "1. Remove people and moving objects from all visible zones.":
    "1. Уберите людей и движущиеся предметы из всех видимых областей.",
  "2. Leave the room.": "2. Покиньте помещение.",
  "3. Start learning. The result below comes from the device.":
    "3. Запустите обучение. Результат ниже приходит от устройства.",
  "All visible zones are clear and the sensor is stationary; I am ready to start learning.":
    "Все видимые области свободны, датчик неподвижен; я готов запустить обучение.",
  "Start background learning": "Начать обучение фона",
  "No message": "Нет сообщения",
  "Automatic coverage map": "Автоматическая карта покрытия",
  "Creates a proposed edge map 0107 from the coverage limits. This is not a confirmed room outline; the proposal is not applied automatically.":
    "Запуск формирует предложение для краевой карты 0107 по пределам покрытия. Это не подтверждённый контур комнаты; предложение не применяется автоматически.",
  "Start detection": "Запустить определение",
  "Proposal received. Open it as a draft and check the map.":
    "Предложение получено. Откройте его как черновик и проверьте карту.",
  "Preview proposal": "Просмотреть предложение",
  "No proposal received yet.": "Предложение ещё не получено.",
  "Connecting to Home Assistant…": "Подключение к Home Assistant…",
  "Aqara FP2 · local control": "Aqara FP2 · локальное управление",
  "● Connected": "● На связи",
  "Map not saved yet": "Карта ещё не сохранена",
  "Refresh from radar": "Обновить с радара",
  Illuminance: "Освещённость",
  Configuration: "Конфигурация",
  "Edit map": "Редактировать карту",
  "Back to zones": "К зонам",
  "Fresh radar data": "Свежие данные радара",
  "Map not read yet or restored from an earlier save":
    "Карта ещё не прочитана или сохранена ранее",
  "Diagnostics and refresh": "Диагностика и обновление",
  "Read all configuration": "Прочитать всю конфигурацию",
  "Waiting for an actual target report.": "Ожидаем реальный отчёт целей.",
  "FP2 · Local control": "FP2 · Локальное управление",
  "Presence map, zones and FP2 radar settings":
    "Карта присутствия, области и настройка радара FP2",
  "Connecting…": "Подключение…",
  "Open radar settings": "Открыть настройку радара",
  "Configure ↗": "Настроить ↗",
  "Presence detected": "Обнаружено присутствие",
  "Presence unknown": "Присутствие неизвестно",
  "No presence": "Нет присутствия",
  "Targets: waiting for a report": "Цели: ожидаем отчёт",
  "Radar zones and live targets": "Зоны радара и живые цели",
  "Open settings and save the configuration from the radar.":
    "Откройте настройку и сохраните конфигурацию с радара.",
  unknown: "неизвестно",
  presence: "присутствие",
  clear: "свободно",
  "Zones — saved map · targets — live":
    "Области — сохранённая карта · цели — живые",
  "Map not saved": "Карта не сохранена",
  "FP2 · Radar overview": "FP2 · Обзор радара",
  "Compact zone map with live targets":
    "Компактная карта областей с живыми целями",
  "No saved configuration. Read it from the radar.":
    "Нет сохранённой конфигурации. Прочитайте её с радара.",
  "Could not load the saved configuration":
    "Не удалось загрузить сохранённую конфигурацию",
  "Configuration read, but saving to HA failed. Refresh again.":
    "Конфигурация прочитана, но сохранение в HA не удалось. Повторите обновление.",
  "This card is read-only": "Карточка только для просмотра",
  "Learning is not complete; commands are paused":
    "Обучение ещё не завершено; команды приостановлены",
  "No fresh confirmed radar read-back":
    "Нет свежего подтверждённого чтения радара",
  "Learning is not complete": "Обучение ещё не завершено",
  "Reading configuration": "Чтение конфигурации",
  "Radar read-back does not match the change":
    "Чтение радара не совпадает с изменением",
  "Change confirmed by reading radar RAM":
    "Изменение подтверждено чтением RAM радара",
  "Start requested. ACK and learning completion appear separately in the radar status.":
    "Запуск запрошен. ACK и завершение обучения отображаются отдельно в статусе радара.",
  "Boundaries / exclusions": "Границы / исключения",
  "Affects coordinate retention and target output.":
    "Влияет на удержание координат и вывод целей.",
  "Entrances/exits": "Входы/выходы",
  "Affects zone state and nearby targets.":
    "Влияет на состояние областей и соседних целей.",
  "Interference sources": "Источники помех",
  "May exclude matching targets from the tracker.":
    "Может исключать подходящие цели из трекера.",
  "Proximity · 0106": "Близость · 0106",
  "Sensitivity · 0111": "Чувствительность · 0111",
  "Coordinate rotation · 0122": "Разворот координат · 0122",
  "Installation angle · 0170": "Угол установки · 0170",
  "Zone {id}": "Зона {id}",
  "Live targets: {count}": "Живые цели: {count}",
  "{seconds} s ago · sequence {sequence}":
    "{seconds} с назад · последовательность {sequence}",
  "{source} · {count} cells": "{source} · {count} ячеек",
  "{value} · unknown code": "{value} · неизвестный код",
  "{value} · history up to {window} samples":
    "{value} · история до {window} отсчётов",
  "0153 · write value (RAM raw: {raw}, inversion 0↔1)":
    "0153 · значение записи (RAM raw: {raw}, инверсия 0↔1)",
  "Write “{label}”: {value}?": "Записать «{label}»: {value}?",
  "Map saved in HA · {date}": "Карта сохранена в HA · {date}",
  "Could not read {count} sections": "Не удалось прочитать {count} разделов",
  "Targets: {count}": "{count} целей",
  "{value} lx": "{value} лк",
  Map: "Карта",
  Settings: "Настройки",
  Learning: "Обучение",
  "Report: {report}. Protocol fields without confirmed physical units.":
    "Отчёт: {report}. Поля протокола без подтверждённых физических единиц.",
  "T{id}: invalid record": "T{id}: некорректная запись",
  "Delete zone {id} from the device?": "Удалить область {id} с устройства?",
  "Device status: {status}": "Состояние устройства: {status}",
  "{status} · Frames: {valid} / rejected {rejected}":
    "{status} · Кадры: {valid} / отклонено {rejected}",
  "Target report: {seconds} s ago · N{count}":
    "Отчёт целей: {seconds} с назад · N{count}",
  "{occupied} / {total} zones occupied": "{occupied} / {total} областей занято",
  Language: "Язык",
  "Follow Home Assistant": "Как в Home Assistant",
  "Entity prefix": "Префикс сущностей",
  "Service prefix": "Префикс сервисов",
  Node: "Узел",
  "Client disposed": "Клиент отключён",
  "Home Assistant unavailable": "Home Assistant недоступен",
  "Zone must be 1…30": "Номер зоны должен быть от 1 до 30",
  "Use deleteZone for empty geometry":
    "Для пустой геометрии используйте удаление области",
  "Unsupported map": "Неподдерживаемая карта",
  "Unsupported scalar value": "Неподдерживаемое значение параметра",
  "Unsupported zone property": "Неподдерживаемый параметр области",
  "Name required": "Укажите название",
  "Unsupported learning action": "Неподдерживаемая команда обучения",
  "Expected 40-byte mask": "Ожидается маска из 40 байт",
  "Expected 320 cells": "Ожидается 320 ячеек",
  "Malformed target payload": "Некорректные данные целей",
  "Malformed target report": "Некорректный отчёт целей",
  "Expected 14-byte target record": "Ожидается запись цели из 14 байт",
} as const;
export type MessageKey = keyof typeof russian;
export type MessageValues = Record<string, string | number>;
export type Language = "en" | "ru";

/** Explicit override wins; unsupported/missing languages use English. */
export function resolveLanguage(
  config: Pick<CardConfig, "language"> = {},
  hass?: Pick<HomeAssistant, "language" | "locale">,
): Language {
  const language =
    config.language || hass?.language || hass?.locale?.language || "en";
  return /^ru(?:[-_]|$)/i.test(language) ? "ru" : "en";
}

export function translate(
  key: string,
  language: Language = "en",
  values: MessageValues = {},
): string {
  const message =
    language === "ru" && Object.hasOwn(russian, key)
      ? russian[key as MessageKey]
      : key;
  return message.replace(/\{(\w+)\}/g, (token, name: string) =>
    Object.hasOwn(values, name) ? String(values[name]) : token,
  );
}

export function formatDate(
  timestamp: number,
  language: Language,
  timeOnly = false,
): string {
  const date = new Date(timestamp);
  return timeOnly
    ? date.toLocaleTimeString(language)
    : date.toLocaleString(language);
}
