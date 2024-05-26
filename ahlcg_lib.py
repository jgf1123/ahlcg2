# -*- coding: utf-8 -*-
"""
Created on Wed Jan  4 15:36:30 2023

@author: jgf11
"""

from collections import defaultdict
import json

class Taboo:
  def __init__(self, taboo_json):
    with open(taboo_json, 'r') as file:
      taboo_json = json.load(file)
    # latest taboo
    self.MAX_TABOO = max([taboo_dict['id'] for taboo_dict in taboo_json])
        
    self.taboo_dict = defaultdict(dict)  # {taboo_id: {card_code: taboo}}
    for taboo in taboo_json:
      taboo_id = taboo['id']
      for taboo_card in json.loads(taboo['cards']):  # parse str into json
        card_code = taboo_card['code']
        self.taboo_dict[taboo_id][card_code] = taboo_card
      
      if taboo['id'] == self.MAX_TABOO:  # if most recent taboo
        # list of card_codes in most recent taboo
        self.tabooed_cards = [card['code']
                              for card in json.loads(taboo['cards'])
                              if 'xp' in card or card['text'] == 'Forbidden.']
      
  def lookup_taboo(self, card_code, taboo_id):
    '''Returns taboo entry for card_code and taboo_id. Returns None if no
    taboo found'''
    if taboo_id not in self.taboo_dict:  # check taboo_id exists
      return None
      
    try:
      return self.taboo_dict[taboo_id][card_code]
    except IndexError:  # return None if card not found
      return None
    
    
class Merge:
  merge_cards = {'01683': '03230',  # map revised core set to original campaign/mythos pack
                 '01684': '02261',
                 '01685': '60227',
                 '01686': '06279',
                 '01687': '03031',
                 '01688': '03234',
                 '01689': '51007',
                 '01690': '03236',
                 '01691': '02308',
                 '01692': '05324',
                 '01693': '02194',
                 '01694': '02158',
                 '01695': '02157',
                 '60108': '01017',  # map investigator starter to original campaign/mythos pack
                 '60110': '06196',
                 '60113': '01023',
                 '60119': '01025',
                 '60212': '02020',
                 '60218': '02186',
                 '60219': '01039',
                 '60307': '01044',
                 '60308': '04107',
                 '60312': '03194',
                 '60313': '03030',
                 '60314': '04232',
                 '60319': '01053',
                 '60405': '02029',
                 '60413': '03034',
                 '60414': '02153',
                 '60417': '04032',
                 '60418': '02190',
                 '60510': '01075',
                 '60514': '04034',
                 '60516': '04200',
                 '60517': '01079',
                 '60519': '04201',
                 '60520': '03114',
                 }
  
  def merge_card_code(self, card_code):
    '''Returns the original card code'''
    # revised core set that duplicates core set
    if '01516' <= card_code <= '01603':
      new_card_code = (card_code[:2]  # first 2 digits
                       + str(int(card_code[2]) - 5)  # subtract 500
                       + card_code[3:])  # last 2 digits
      return new_card_code
    else:
      try:
        return self.merge_cards[card_code]
      except KeyError:
        return card_code
  