class User:
    def __init__(self, user_id: int, username: str, email: str, password: str) -> None:
        self.user_id = user_id
        self.username = username
        self.email = email
        self.password = password

    def to_dict(self):
        return self.__dict__

if __name__ == "__main__":
    user = User(1, "JohnnyTest", "johnny@mail.com", "Johnny1sDaBest")
    print(user.to_dict())