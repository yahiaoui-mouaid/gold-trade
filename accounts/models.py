from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q


class UserManager(BaseUserManager):
    def create_user(self, username, password, role, display_name=""):
        user = self.model(username=username, role=role, display_name=display_name or username)
        user.set_password(password)
        user.save()
        return user


class User(AbstractBaseUser):
    OWNER = "owner"
    SALESMAN = "salesman"
    ROLES = [(OWNER, "Owner"), (SALESMAN, "Salesman")]

    username = models.CharField(max_length=150, unique=True)
    display_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=ROLES)
    is_active = models.BooleanField(default=True)
    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "username"
    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role"], condition=Q(role="owner"), name="one_owner_only"),
        ]

    @property
    def is_owner(self):
        return self.role == self.OWNER


class BackupCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="backup_codes")
    code_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reset_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
