import os

from modagent.config import Tier, current_edition, entitlement_tier


def main():
    previous = os.environ.get("MODAGENT_EDITION")
    try:
        os.environ["MODAGENT_EDITION"] = "free"
        assert current_edition() == "free"
        assert entitlement_tier() == Tier.FREE

        os.environ["MODAGENT_EDITION"] = "subscription"
        assert current_edition() == "subscription"
        assert entitlement_tier() == Tier.PRO
    finally:
        if previous is None:
            os.environ.pop("MODAGENT_EDITION", None)
        else:
            os.environ["MODAGENT_EDITION"] = previous

    for feature in (
        "search",
        "download",
        "install",
        "rollback",
        "patch",
        "structured_recommendations",
    ):
        assert Tier.can(Tier.FREE, feature), feature
        assert Tier.can(Tier.PRO, feature), feature

    for feature in ("subscription_experience",):
        assert not Tier.can(Tier.FREE, feature), feature
        assert Tier.can(Tier.PRO, feature), feature

    assert not Tier.can(Tier.PRO, "builtin_llm")
    print("EDITION CAPABILITY TESTS PASSED")


if __name__ == "__main__":
    main()
