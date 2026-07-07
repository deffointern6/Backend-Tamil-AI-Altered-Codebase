import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database.db import get_db
from database.models_db import User, RefreshToken, Account
from auth.hash import hash_password, verify_password
from auth.jwt import create_access_token, generate_refresh_token
from auth.dependencies import get_current_user
from settings.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

# --- PYDANTIC MODELS ---
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class RefreshRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    is_active: bool

    class Config:
        from_attributes = True


class AccountProfileResponse(BaseModel):
    username: str
    email: str
    display_name: str | None = None
    phone_number: str | None = None
    dob: str | None = None

    class Config:
        from_attributes = True


class AccountProfileUpdate(BaseModel):
    display_name: str | None = None
    phone_number: str | None = None
    dob: str | None = None


# --- HELPER FUNCTIONS ---
def create_and_save_refresh_token(user_id: str, db: Session) -> str:
    """
    Generates a secure refresh token, saves it to the database with expiration, and returns it.
    """
    token_str = generate_refresh_token()
    expires_at = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    
    db_token = RefreshToken(
        token=token_str,
        user_id=user_id,
        expires_at=expires_at
    )
    db.add(db_token)
    db.commit()
    return token_str


# --- REGISTER ROUTE ---
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(request: UserRegister, db: Session = Depends(get_db)):
    # Check if username exists
    existing_username = db.query(User).filter(User.username == request.username).first()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
        
    # Check if email exists
    existing_email = db.query(User).filter(User.email == request.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
        
    # Create new user
    hashed = hash_password(request.password)
    new_user = User(
        username=request.username,
        email=request.email,
        hashed_password=hashed
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Automatically create the associated Account record
    new_account = Account(
        user_id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        display_name=new_user.username,  # Default display name to username
        phone_number="",
        dob=""
    )
    db.add(new_account)
    db.commit()
    
    return new_user


# --- JSON-BASED LOGIN ROUTE ---
@router.post("/login", response_model=TokenResponse)
def login_user(request: UserLogin, db: Session = Depends(get_db)):
    # Find user by username or email
    user = db.query(User).filter(
        (User.username == request.username) | (User.email == request.username)
    ).first()
    
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive"
        )
        
    # Generate tokens
    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_and_save_refresh_token(user.id, db)
    
    return {
        "access_token": access_token, 
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


# --- OAUTH2 FORM-BASED LOGIN ROUTE (For Swagger /docs Authorize button) ---
@router.post("/token", response_model=TokenResponse)
def login_for_oauth2_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(
        (User.username == form_data.username) | (User.email == form_data.username)
    ).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive"
        )
        
    # Generate tokens
    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_and_save_refresh_token(user.id, db)
    
    return {
        "access_token": access_token, 
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


# --- REFRESH TOKEN ROUTE ---
@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(request: RefreshRequest, db: Session = Depends(get_db)):
    # Find active token
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token == request.refresh_token,
        RefreshToken.is_revoked == False
    ).first()
    
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
        
    if db_token.expires_at < datetime.utcnow():
        # Clean up expired token
        db_token.is_revoked = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired"
        )
        
    # Load user
    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is inactive or deleted"
        )
        
    # Revoke/rotate the used refresh token (Token Rotation)
    db_token.is_revoked = True
    db.commit()
    
    # Generate brand new tokens
    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = create_and_save_refresh_token(user.id, db)
    
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }


# --- LOGOUT ROUTE ---
@router.post("/logout", status_code=status.HTTP_200_OK)
def logout_user(request: RefreshRequest, db: Session = Depends(get_db)):
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token == request.refresh_token
    ).first()
    
    if db_token:
        # Revoke the token
        db_token.is_revoked = True
        db.commit()
        
    return {"status": "success", "message": "Successfully logged out"}


# --- CURRENT USER PROFILE ROUTE ---
@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


def validate_and_format_dob(dob_str: str | None) -> str:
    if not dob_str:
        return ""
    # If it is in YYYY-MM-DD format (ISO), convert to dd/mm/yyyy
    if re.match(r"^\d{4}-\d{2}-\d{2}$", dob_str):
        parts = dob_str.split("-")
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    # If it is in dd/mm/yyyy format, return it
    if re.match(r"^\d{2}/\d{2}/\d{4}$", dob_str):
        return dob_str
    # Otherwise raise an error
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid date of birth format. Must be DD/MM/YYYY or YYYY-MM-DD."
    )


# --- USER ACCOUNT PROFILE ENDPOINTS ---
@router.get("/account", response_model=AccountProfileResponse)
def get_account_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    account = db.query(Account).filter(Account.user_id == current_user.id).first()
    if not account:
        # Create default profile for legacy users
        account = Account(
            user_id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            display_name=current_user.username,
            phone_number="",
            dob=""
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


@router.put("/account", response_model=AccountProfileResponse)
def update_account_profile(
    profile_data: AccountProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    account = db.query(Account).filter(Account.user_id == current_user.id).first()
    if not account:
        account = Account(
            user_id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            display_name=current_user.username,
            phone_number="",
            dob=""
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        
    if profile_data.display_name is not None:
        account.display_name = profile_data.display_name
        
    if profile_data.phone_number is not None:
        account.phone_number = profile_data.phone_number
        
    if profile_data.dob is not None:
        account.dob = validate_and_format_dob(profile_data.dob)
        
    db.commit()
    db.refresh(account)
    return account


