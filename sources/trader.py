"""
Trade bot module
"""

import json
import re
import time
import traceback
import urllib.parse
from threading import Thread
from typing import Optional

import requests
from vk_api import VkApi
from vk_api.longpoll import Event, VkLongPoll, VkEventType


class TradeSlot:
    """ Simple slot description """
    name: str = ""
    short: str = ""
    cost: int = 0
    code: int = 0

    def __repr__(self):
        return [self.name, self.cost, self.short, self.code].__str__()


class TradeLot:
    """ Simple lot description """
    cost: int = 0
    count: int = 0
    lotnum: int = 0


class TraderApi:
    """ Trader through Saymon say """

    API_URL = "https://vip3.activeusers.ru/app.php?act=%s&auth_key=%s&group_id=182985865&api_id=7055214"
    ACT_TYPE_ITEM = "item&id=%s"
    RE_LOT = r"(\d+)\*(.+?) - (\d+) золота \((\d+)\)"

    def __init__(self, bagid: str):
        self.bagid = bagid
        self.relot = self.compile(self.RE_LOT)

    def compile(self, pattern: str):
        """ Compile the regular expression """
        return re.compile(pattern, re.IGNORECASE | re.UNICODE | re.DOTALL | re.MULTILINE)

    def buildQuery(self, data):
        """ Build PHP Array from JS Array """
        m_parents = list()
        m_pairs = dict()

        def renderKey(parents: list):
            """ Key decoration """
            depth, out_str = 0, ''
            for x in parents:
                s = "[%s]" if depth > 0 or isinstance(x, int) else "%s"
                out_str += s % str(x)
                depth += 1
            return out_str

        def r_urlencode(rawurl: str):
            """ Encode URL """
            if isinstance(rawurl, list) or isinstance(rawurl, tuple):
                for tmp_index in range(len(rawurl)):
                    m_parents.append(tmp_index)
                    r_urlencode(rawurl[tmp_index])
                    m_parents.pop()
            elif isinstance(rawurl, dict):
                for tmp_key, tmp_value in rawurl.items():
                    m_parents.append(tmp_key)
                    r_urlencode(tmp_value)
                    m_parents.pop()
            else:
                m_pairs[renderKey(m_parents)] = str(rawurl)
            return m_pairs

        return urllib.parse.urlencode(r_urlencode(data))

    def buildHeaders(self, length: int, referer: str):
        """ Request header """
        tmp_params = {
            'Host': 'vip3.activeusers.ru',
            'Connection': 'keep-alive',
            'sec-ch-ua': '"Google Chrome";v="89", "Chromium";v="89", ";Not A Brand";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'DNT': '1',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://vip3.activeusers.ru',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': referer,
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        if length > 0:
            tmp_params['Content-Length'] = str(length)
        # Completed array
        return tmp_params

    def queryLots(self, itemid: int):
        """ Translate item params """
        tmp_referer = self.API_URL % (self.ACT_TYPE_ITEM % itemid, self.bagid)
        tmp_response = requests.get(self.API_URL % (self.ACT_TYPE_ITEM % itemid, self.bagid), headers=self.buildHeaders(0, tmp_referer))
        if not tmp_response.ok:
            return False
        # Item defense
        tmp_params = re.search(r"window.pv624 = ({.+})", tmp_response.text)
        if not tmp_params:
            return False
        tmp_params = json.loads(tmp_params[1])
        tmp_params = {
            "code": "51132l145l691d2fbd8b124d57",
            "pwid": "w_171",
            "context": 1,
            "hash": "",
            "channel": "",
            "vars": tmp_params
        }
        tmp_params = self.buildQuery(tmp_params)
        tmp_response = requests.post(self.API_URL % ("a_program_run", self.bagid), tmp_params, headers=self.buildHeaders(len(tmp_params), tmp_referer))
        if (not tmp_response.ok) or (json.loads(tmp_response.text)["result"] != 1):
            return False
        # Crop items
        tmp_reitems = self.relot.findall(tmp_response.text)
        tmp_lots = []
        for tmp_reitem in tmp_reitems:
            tmp_lot = TradeLot()
            tmp_lot.count = int(tmp_reitem[0])
            tmp_lot.cost = int(tmp_reitem[2])
            tmp_lot.lotnum = int(tmp_reitem[3])
            tmp_lots.append(tmp_lot)
        return tmp_lots


class Trader:
    """ Движок обработки торговли """

    # Идентификатор торгового бота
    TRADE_BOT_ID = -183040898

    # Идентификатор игрового бота
    GAME_BOT_ID = -182985865

    # Имя файла данных
    DATA_NAME = "data.txt"

    def __init__(self, token: str, bagid: str, ownerid: int, ownertoken: str = ""):
        """ Конструктор """
        if ownertoken:
            self.ownersession = VkApi(token=ownertoken)
            self.ownerlongpoll = VkLongPoll(self.ownersession)
            self.threadlpowner = Thread(target=self.lpownerthread)
        else:
            self.ownersession = None
            self.ownerlongpoll = None
            self.threadlpowner = None
        self.ownerid = ownerid
        self.tradersession = VkApi(token=token)
        self.traderlongpoll = VkLongPoll(self.tradersession)
        self.traderapi = TraderApi(bagid)
        self.lots = []
        self.lotkey = 0
        self.event: Optional[Event] = None
        self.reg_all = self.traderapi.compile(r"^скупка кажи")
        self.reg_set = self.traderapi.compile(r"^скупка (.+?) (\d+)")
        self.reg_accept = self.traderapi.compile(r"^⚖.+Вы успешно приобрели с аукциона предмет (\d+)\*(.+) -")
        self.threadbuy = Thread(target=self.buythread)
        self.threadlptrader = Thread(target=self.lptraderthread)
        self.load()
        self.run()

    def run(self):
        """ Запуск жизненного цикла """
        print("> Ready")
        if self.threadbuy:
            self.threadbuy.start()
        if self.threadlptrader:
            self.threadlptrader.start()
        if self.threadlpowner:
            self.threadlpowner.start()

    def buythread(self):
        """ Покупка в потоке """
        while True:
            try:
                self.buy()
            except Exception as e:
                print("Buy failed %s %s" % (e, traceback.format_exc().replace("\n", " ")))
                time.sleep(3)

    def lptraderthread(self):
        """ Trader long poll thread """
        while True:
            try:
                for self.event in self.traderlongpoll.check():
                    if self.event.type == VkEventType.MESSAGE_NEW:
                        self.checktrader()
                        if not self.ownerlongpoll:
                            self.checkowner()
            except Exception as e:
                print("Read trade failed %s %s" % (e, traceback.format_exc().replace("\n", " ")))
                time.sleep(3)

    def lpownerthread(self):
        """ Trader long poll thread """
        while True:
            try:
                for self.event in self.ownerlongpoll.check():
                    if self.event.type == VkEventType.MESSAGE_NEW:
                        self.checkowner()
            except Exception as e:
                print("Read owner failed %s %s" % (e, traceback.format_exc().replace("\n", " ")))
                time.sleep(3)

    def load(self):
        """ Загрузка БД из файла """
        with open(self.DATA_NAME, 'r', encoding='utf-8') as tmpFile:
            tmp_items = json.load(tmpFile)
            for tmp_item in tmp_items:
                tmp_slot = TradeSlot()
                tmp_slot.name = tmp_item[0]
                tmp_slot.cost = tmp_item[1]
                tmp_slot.short = tmp_item[2]
                tmp_slot.code = tmp_item[3]
                self.lots.append(tmp_slot)

    def save(self):
        """ Сохранение БД в файл """
        with open(self.DATA_NAME, 'w', encoding='utf-8') as tmp_file:
            tmp_file.write("[\n")
            tmp_len = len(self.lots)
            for tmp_i in range(tmp_len):
                tmp_file.write(self.lots[tmp_i].__str__().replace("'", '"'))
                if tmp_i < tmp_len - 1:
                    tmp_file.write(",")
                tmp_file.write("\n")
            tmp_file.write("]")

    def send(self, session: VkApi, text: str, channel: int):
        """ Отправка сообщения """
        tmpParams = {
            'peer_id': channel,
            'message': text,
            'random_id': 0
        }
        try:
            session.method('messages.send', tmpParams)
        except Exception as e:
            print(e)

    def checktrader(self):
        """ Проверка текущего сообщения торговца """
        if self.showall():
            return
        if self.setcost():
            return

    def checkowner(self):
        """ Проверка текущего сообщения владельца """
        if self.checktrade():
            return

    def showall(self):
        """ Отображение списка товаров """
        if not self.event.from_user:
            return False
        if self.event.user_id != self.ownerid:
            return False
        # Пробьем регулярку
        tmp_match = self.reg_all.search(self.event.message)
        if not tmp_match:
            return False
        # Подготовим
        tmp_data = ""
        for tmp_item in self.lots:
            if tmp_item.cost > 0:
                tmp_data += "%s: %s\n" % (tmp_item.name, tmp_item.cost)
        # Отправим
        self.send(self.tradersession, tmp_data, self.ownerid)
        # Готово
        return True

    def setcost(self):
        """ Установка цены """
        if not self.event.from_user:
            return False
        if self.event.user_id != self.ownerid:
            return False
        # Пробьем регулярку
        tmp_match = self.reg_set.search(self.event.message)
        if not tmp_match:
            return False
        # Определим
        tmp_slot: Optional[TradeSlot] = None
        tmp_name = tmp_match[1]
        tmp_cost = int(tmp_match[2])
        # Поищем основное
        for tmp_search in self.lots:
            if (tmp_search.short == tmp_name) or (tmp_search.name == tmp_name):
                tmp_slot = tmp_search
                break
        # Установим
        if not tmp_slot:
            self.send(self.tradersession, "😨%s нет в базе" % tmp_name, self.ownerid)
            return True
        tmp_slot.cost = tmp_cost
        self.save()
        self.send(self.tradersession, "👍🏻%s сохранено" % tmp_name, self.ownerid)
        # Готово
        return True

    def checktrade(self):
        """ Учет покупки """
        if self.event.peer_id != self.GAME_BOT_ID:
            return False
        # Пробьем регулярку
        tmp_match = self.reg_accept.search(self.event.message)
        if not tmp_match:
            return False
        # Учет покупки
        tmp_count = int(tmp_match[1])
        tmp_name = tmp_match[2].lower()
        print("  Куплен %s %s" % (tmp_count, tmp_name))
        # Успешно
        return True

    def buyinc(self, pause: bool):
        """ Inc current key """
        if self.lotkey == len(self.lots) - 1:
            self.lotkey = 0
        else:
            self.lotkey += 1
        if pause:
            time.sleep(6)

    def buy(self):
        """ Покупка """
        tmp_lot: TradeLot
        # Запросим с сервера
        tmp_slot: TradeSlot = self.lots[self.lotkey]
        if tmp_slot.code <= 0:
            return self.buyinc(False)
        if tmp_slot.cost <= 0:
            return self.buyinc(False)
        print("> query " + tmp_slot.name)
        tmp_lots = self.traderapi.queryLots(tmp_slot.code)
        if not tmp_lots:
            return self.buyinc(True)
        print("> found " + str(len(tmp_lots)))
        # Переберем лоты
        for tmp_lot in tmp_lots:
            if tmp_slot.cost < tmp_lot.cost / tmp_lot.count:
                continue
            print("Лот %s запрос %s %s за %s" % (tmp_lot.lotnum, tmp_lot.count, tmp_slot.name, tmp_lot.cost))
            if self.ownersession:
                self.send(self.ownersession, "Купить лот %s" % tmp_lot.lotnum, self.GAME_BOT_ID)
            else:
                self.send(self.tradersession, "Купить лот %s" % tmp_lot.lotnum, self.GAME_BOT_ID)
            return time.sleep(6)
        # Следующий
        self.buyinc(True)
