import pytest
from policy_factory import PolicyServer, PolicySigner
from vethuq_core.policy import PolicyKeys


@pytest.fixture
def signer():
    return PolicySigner("policy-1")


@pytest.fixture
def standby():
    return PolicySigner("standby-1", standby=True)


@pytest.fixture
def keys(signer, standby):
    return PolicyKeys([signer.key(), standby.key()])


@pytest.fixture
def server():
    srv = PolicyServer().start()
    yield srv
    srv.stop()
