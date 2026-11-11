def role(request):
    user = getattr(request, "user", None)
    authenticated = user is not None and user.is_authenticated
    return {"is_owner": authenticated and user.is_owner}
