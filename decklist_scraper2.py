# -*- coding: utf-8 -*-
"""
Created on Thu Sep  3 19:52:12 2020

@author: jgf1123
"""

import pickle
import requests

DECKLIST_JSON_PICKLE = 'decklist_json.pickle'
decklist_json = pickle.loads(open(DECKLIST_JSON_PICKLE, "rb").read())

decklist_id = 35234  # 35234
while decklist_id >= 15614:  # 2019-09-29
    if decklist_id not in decklist_json:
        try:
            response = requests.get('http://arkhamdb.com/api/public/decklist/{}.json'.format(decklist_id))
            if response.status_code == 200:
                if len(response.text) > 0:
                    print(decklist_id)
                    decklist_json[decklist_id] = response.json()
                else:
                    print('{} empty'.format(decklist_id))
                    decklist_json[decklist_id] = None
        except ConnectionError:
            print('ConnectionError')
    decklist_id -= 1

with open(DECKLIST_JSON_PICKLE, "wb") as djf:
    djf.write(pickle.dumps(decklist_json))