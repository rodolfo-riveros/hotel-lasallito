"""Backend de autenticación con caché del usuario (RNF-REN-01).

Django carga el usuario en cada página. Con la base en la nube eso cuesta una
consulta (~200 ms), así que se guarda en la caché y se invalida con la misma
versión que los permisos (cualquier cambio de usuario, rol o acceso).
"""

from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache

from .cache import TTL, _key


class CachedModelBackend(ModelBackend):
    def get_user(self, user_id):
        key = _key("user", user_id)
        user = cache.get(key)
        if user is None:
            user = super().get_user(user_id)
            if user is not None:
                cache.set(key, user, TTL)
        return user
