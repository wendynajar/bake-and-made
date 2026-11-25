"""Formularios de la app de usuarios."""

import re
from typing import Any

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import PerfilVIP

# Espacios, guiones, puntos y paréntesis que la gente suele escribir en un teléfono.
_SEPARADORES_TELEFONO = re.compile(r'[\s\-.()]')


class RegistroUsuarioForm(UserCreationForm):
    """Registro de cliente con nombre, apellidos, teléfono y correo obligatorio y único.

    El correo se exige único (sin distinguir mayúsculas) porque será el canal
    de contacto para pedidos y recordatorios. El teléfono (10 dígitos, México)
    no es campo de `User`: se guarda en `PerfilVIP.telefono`.
    """

    field_order = [
        'username', 'first_name', 'last_name', 'email', 'telefono', 'password1', 'password2',
    ]

    username = forms.CharField(
        max_length=150,
        required=True,
        label="Nombre de usuario",
        help_text="Máximo 150 caracteres. Puedes utilizar letras, números y los símbolos @/./+/-/_"
    )

    email = forms.EmailField(
        required=True,
        label="Correo electrónico"
    )

    first_name = forms.CharField(
        max_length=150,
        required=True,
        label="Nombre"
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
        label="Apellidos"
    )

    telefono = forms.CharField(
        max_length=20,
        required=True,
        label="Teléfono",
        help_text="10 dígitos, sin lada internacional.",
        widget=forms.TextInput(attrs={
            'type': 'tel', 'autocomplete': 'tel-national', 'inputmode': 'numeric',
        }),
    )

    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput,
        help_text="La contraseña debe contener al menos 8 caracteres, no puede ser demasiado común ni completamente numérica."
    )

    password2 = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput,
        help_text="Ingresa nuevamente tu contraseña para confirmar."
    )

    class Meta:
        model = User
        fields = (
            'username',
            'first_name',
            'last_name',
            'email',
            'password1',
            'password2'
        )

    def clean_email(self) -> str:
        """Normaliza el correo y rechaza los que ya estén registrados."""
        email =self.cleaned_data['email'].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Este correo electrónico ya está registrado."
            )

        return email

    def clean_telefono(self) -> str:
        """Quita separadores y exige exactamente 10 dígitos (número nacional de México)."""
        telefono = _SEPARADORES_TELEFONO.sub('', self.cleaned_data['telefono'])
        if not re.fullmatch(r'\d{10}', telefono):
            raise forms.ValidationError("Escribe un teléfono de 10 dígitos.")
        return telefono

    def save(self, commit: bool = True) -> Any:
        """Crea el usuario y guarda su teléfono en el perfil.

        Con `commit=False` el usuario aún no existe en la base, así que el perfil
        no se puede crear; quien llame debe guardarlo después.
        """
        usuario = super().save(commit=commit)
        if commit:
            perfil = PerfilVIP.de(usuario)
            perfil.telefono = self.cleaned_data['telefono']
            perfil.save(update_fields=['telefono'])
        return usuario
