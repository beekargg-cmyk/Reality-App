import enum
from sqlalchemy import Column, Integer, String, Enum, ForeignKey, JSON, Boolean, DateTime, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class ClusterType(str, enum.Enum):
    standard = "standard"
    tunnel = "tunnel"

class ServerRole(str, enum.Enum):
    entry = "entry"
    exit = "exit"
    standalone = "standalone"

class Cluster(Base):
    __tablename__ = "clusters"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    type = Column(Enum(ClusterType), default=ClusterType.standard)
    brand_name = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    
    
    servers = relationship("Server", back_populates="cluster", cascade="all, delete-orphan")
    users = relationship("User", back_populates="cluster", cascade="all, delete-orphan")

class Server(Base):
    __tablename__ = "servers"
    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=False)
    
    name = Column(String, nullable=False)
    ip = Column(String, nullable=False)
    
    # ПОРТ УПРАВЛЕНИЯ (SSH)
    ssh_port = Column(Integer, default=22)
    ssh_user = Column(String, default="root")
    ssh_password = Column(String, nullable=True)
    ssh_private_key = Column(String, nullable=True)
    
    # VPN CONFIG
    public_key = Column(String, nullable=True) # <-- Updated to True
    short_id = Column(String, default="")
    role = Column(Enum(ServerRole), default=ServerRole.standalone)
    
    # !!! ДОБАВИЛ ПОЛЕ ТОКЕНА !!!
    api_token = Column(String, default="changeme", nullable=False) 
    
    inbounds = Column(JSON, default=list)
    # CASCADE CONFIG
    config = Column(JSON, default={}) # Stores TUNNEL_PASS, OUTBOUND_IPS
    parent_id = Column(Integer, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True) # For Entry -> Exit link
    exit_port = Column(Integer, default=50050)  # Порт туннеля для Exit Node (разные порты для multi-exit)

    # Статистика
    cpu = Column(Integer, default=0)
    ram = Column(Integer, default=0)
    disk = Column(Integer, default=0)
    online_users = Column(Integer, default=0)
    user_limit = Column(Integer, default=100) 
    last_seen = Column(DateTime(timezone=True), nullable=True)
    net_rx = Column(BigInteger, default=0)  # Network RX bytes
    net_tx = Column(BigInteger, default=0)  # Network TX bytes
    metered = Column(Boolean, default=False)  # Тарификация трафика
    
    # HOSTER INTEGRATION (for automated IP swap)
    hoster = Column(String, nullable=True)     # "play2go" | "ufo" | "iwi" | null
    hoster_vm_id = Column(Integer, nullable=True)  # VM ID on the hoster's side
    
    # Location-based balancing
    location = Column(String, nullable=True)  # ISO country code: 'de', 'es', 'us', etc.
    
    # DOUBLE-HOP RELAY: if set, Entry sends traffic to relay_through server, which forwards to this Exit
    relay_through_id = Column(Integer, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    
    # Multi-SNI: пул SNI доменов для ротации через диагностику
    available_snis = Column(JSON, default=list)
    
    cluster = relationship("Cluster", back_populates="servers")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True)
    telegram_id = Column(BigInteger, index=True, nullable=True) # Для связи с ботом
    cluster_id = Column(Integer, ForeignKey("clusters.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    cluster = relationship("Cluster", back_populates="users")
    
    # Лимиты и срок действия
    traffic_limit = Column(BigInteger, default=0) # 0 = Unlimited
    expires_at = Column(DateTime(timezone=True), nullable=True)
    hwid = Column(JSON, nullable=True)  # JSON-массив HWID (до 3 устройств)
    hwid_agents = Column(JSON, nullable=True) # Маппинг HWID -> User-Agent
    device_limit = Column(Integer, default=1)  # Лимит устройств (1 базовый, 2-3 за доп. подписки)
    
    # Статистика
    last_traffic_up = Column(BigInteger, default=0)
    last_traffic_down = Column(BigInteger, default=0)
    traffic_blocked = Column(Boolean, default=False)  # Заблокирован по лимиту трафика
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    
    # Per-user SNI preferences (populated by diagnostics)
    # Format: {"server_id": {"sni": "best.domain.com", "updated_at": "...", "source": "diagnostics"}}
    sni_preferences = Column(JSON, nullable=True)

    @property
    def is_online(self):
        if not self.last_active_at:
            return False
        # Простая проверка: если активность была в последние 15 минут
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        # Если last_active_at без таймзоны, приводим, иначе сравниваем как есть
        if self.last_active_at.tzinfo is None:
             return (datetime.utcnow() - self.last_active_at) < timedelta(minutes=15)
        return (now - self.last_active_at) < timedelta(minutes=15)
