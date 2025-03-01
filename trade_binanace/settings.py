"""
Django settings for trade_binanace project.

Generated by 'django-admin startproject' using Django 5.1.5.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.1/ref/settings/
"""

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-6m-cefe+gzl_8=i(eq(il2ww+nev@_1q5a78pa&!o_2ht5cyvr'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    "tailwind",
    "django_htmx",
    'core',
    'django_extensions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'trade_binanace.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "core/templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'trade_binanace.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'trade_binance',
        'USER': 'postgres',
        'PASSWORD': 'Poiuytreza@59',
        'HOST': 'localhost',
        'PORT': '5432',
        'OPTIONS': {
            'options': '-c client_encoding=UTF8',
        }
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ⚙️ Paramètres de Régulation des Monnaies
SEUIL_MIN_TRAITEMENT = 0.5  # Seuil min en secondes
DUREE_SURVEILLANCE_MIN = 30  # Durée avant d'ajouter une monnaie

SEUIL_MAX_TRAITEMENT = 3.0  # Seuil max en secondes
DUREE_SURVEILLANCE_MAX = 60  # Durée avant de réduire les monnaies

SEUIL_CRITIQUE = 5.0  # Seuil critique de surcharge
DUREE_SURVEILLANCE_CRITIQUE = 30  # Réaction plus rapide en cas de surcharge sévère

NB_MONNAIES_MAX = 50  # Maximum de monnaies simultanées
NB_MONNAIES_MIN = 5  # Minimum de monnaies actives
REDUCTION_NB_MONNAIES = 3  # Nombre de monnaies à retirer en cas de surcharge

# ⚙️ Gestion des WebSockets et Threads
MAX_QUEUE = 10
MAX_STREAM_PER_WS = 5
DUREE_LIMITE_ORDRE = 2  # Temps max en secondes pour un ordre

# ⚙️ Gestion du Flush des Klines
NB_MESSAGES_FLUSH = 25
DUREE_MAX_FLUSH = 5  # Temps max avant flush

# ⚙️ Récupération de l'historique
NB_KLINES_HISTORIQUE = 100  # Nombre de Klines à charger par intervalle
