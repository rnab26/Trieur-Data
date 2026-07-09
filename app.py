import streamlit as st
import pandas as pd
import numpy as np
import io
import unicodedata
import re
from difflib import SequenceMatcher

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

DEFAULT_MASTER_COLUMNS = [
    "NOM", "PRENOM", "GENRE/CIVILITE", "VILLE", "CP", "ADRESSE",
    "TELEPHONE MOBILE", "TELEPHONE FIXE", "EMAIL", "DATE DE NAISSANCE", "Source Data"
]

SYNONYMES = {
    "NOM": ["nom", "lastname", "surname", "last_name", "family_name", "patronyme"],
    "PRENOM": ["prenom", "prénom", "firstname", "first_name", "given_name"],
    "GENRE/CIVILITE": ["genre", "civilite", "civilité", "sexe", "sex", "title", "salutation"],
    "VILLE": ["ville", "city", "commune", "locality"],
    "CP": ["cp", "codepostal", "code_postal", "postalcode", "zipcode", "zip", "postal"],
    "ADRESSE": ["adresse", "address", "rue", "street", "location"],
    "TELEPHONE MOBILE": ["telephoneportable", "portable", "mobile", "gsm", "cell", "cellphone", "phone_mobile"],
    "TELEPHONE FIXE": ["telephonefixe", "fixe", "phone", "homephone", "landline", "phone_fixe"],
    "EMAIL": ["email", "e-mail", "mail", "courriel", "e_mail"],
    "DATE DE NAISSANCE": ["datedenaissance", "date_naissance", "naissance", "dob", "birthdate", 
