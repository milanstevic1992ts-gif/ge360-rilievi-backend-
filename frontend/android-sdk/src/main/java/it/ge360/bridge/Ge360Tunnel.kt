package it.ge360.bridge

import com.wireguard.android.backend.Tunnel

internal class Ge360Tunnel(
    private val tunnelName: String = "ge360",
    private val stateListener: (Tunnel.State) -> Unit = {},
) : Tunnel {
    override fun getName(): String = tunnelName

    override fun onStateChange(newState: Tunnel.State) {
        stateListener(newState)
    }
}
