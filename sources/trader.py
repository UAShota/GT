"""
Trade bot module
"""
import datetime
import json
import random
import re
import threading
import time
import urllib.parse

import requests


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

    def log(self, message: str):
        """ Log message """
        print("%s: %s" % (datetime.datetime.now(), message))

    def queryLots(self, itemid: int, itemname: str):
        """ Translate item params """
        tmp_referer = self.API_URL % (self.ACT_TYPE_ITEM % itemid, self.bagid)
        tmp_response = requests.get(self.API_URL % (self.ACT_TYPE_ITEM % itemid, self.bagid), headers=self.buildHeaders(0, tmp_referer))
        if not tmp_response.ok:
            self.log("%s failed item %d query" % (self.bagid, itemid))
            return False
        # Item defense
        tmp_params = re.search(r"window.pv\d+ = ({.+})", tmp_response.text)
        if not tmp_params:
            self.log("%s failed item %d params" % (self.bagid, itemid))
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
            self.log("%s failed item %d program %s" % (self.bagid, itemid, tmp_response.text))
            return False
        # Fail
        if "🚫" in tmp_response.text:
            self.log("%s @ %s" % (self.bagid, json.loads(tmp_response.text)))
            return time.sleep(1800)
        # Crop items
        tmp_reitems = self.relot.findall(tmp_response.text)
        tmp_lots = []
        for tmp_reitem in tmp_reitems:
            tmp_lots.append([int(tmp_reitem[0]), int(tmp_reitem[2]), int(tmp_reitem[3])])
        return [datetime.datetime.now().timestamp(), tmp_lots, itemname]


class Trader:
    """ Движок обработки торговли """

    # Имя файла данных
    DATA_NAME = "data.txt"
    # Export filename
    EXPORT_NAME = "../../var/www/html/export.txt"
    # Export jsname
    EXPORT_NAME_JS = "../../var/www/html/export.js"

    def __init__(self, bagids: []):
        """ Конструктор """
        self.lots = []
        self.data = {}
        self.lotkey = 0
        self.bagids = bagids
        self.locker = threading.Lock()
        self.load()
        self.save()

        for tmp_bagid in bagids:
            threading.Thread(target=self.run, args=(TraderApi(tmp_bagid),)).start()
            time.sleep(random.randint(5, 20))

    def load(self):
        """ Загрузка БД из файла """
        with open(self.DATA_NAME, 'r', encoding='utf-8') as tmpFile:
            self.lots = json.load(tmpFile)
        with open(self.EXPORT_NAME, 'r', encoding='utf-8') as tmpFile:
            self.data = json.load(tmpFile)

    def save(self):
        """ Saving dump """
        with open(self.EXPORT_NAME, 'w', encoding='utf-8') as tmp_file:
            json.dump(self.data, tmp_file, ensure_ascii=False)
        with open(self.EXPORT_NAME_JS, 'w', encoding='utf-8') as tmp_file:
            tmp_file.write("var GData = {")
            for tmp_item in self.data:
                tmp_lot = self.data[tmp_item]
                if not tmp_lot:
                    continue
                if not tmp_lot[1]:
                    continue
                tmp_file.write(str(tmp_item))
                tmp_file.write(":['")
                tmp_file.write(datetime.datetime.fromtimestamp(tmp_lot[0]).strftime("%H:%M:%S"))
                tmp_file.write("',")
                tmp_file.write(tmp_lot[1].__str__())
                tmp_file.write(",'")
                if len(tmp_lot) < 3:
                    tmp_file.write(tmp_lot[0].__str__())
                else:
                    tmp_file.write(tmp_lot[2])
                tmp_file.write("'],")
            tmp_file.write("};")
        pass

    def run(self, bagapi: TraderApi):
        """ Запуск жизненного цикла """
        print("> Ready " + bagapi.bagid)
        while True:
            self.loadnext(bagapi)
            time.sleep(60 / 30 * 60 + random.randint(30, 60))

    def loadinc(self):
        """ Inc current key """
        if self.lotkey == len(self.lots) - 1:
            self.lotkey = 0
        else:
            self.lotkey += 1

    def loadnext(self, bagapi: TraderApi):
        """ Load next item """
        self.locker.acquire()
        try:
            tmp_code = self.lots[self.lotkey][3]
            tmp_name = self.lots[self.lotkey][0]
            self.loadinc()
        finally:
            self.locker.release()
        # Current damp
        tmp_lots = bagapi.queryLots(tmp_code, tmp_name)
        if not tmp_lots:
            return
        # Saving
        self.locker.acquire()
        try:
            self.data[str(tmp_code)] = tmp_lots
            self.save()
        finally:
            self.locker.release()
