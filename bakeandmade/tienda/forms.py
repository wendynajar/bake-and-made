from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User



class RegistroUsuarioForm(UserCreationForm):
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

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Este correo electrónico ya está registrado."
            )

        return email
