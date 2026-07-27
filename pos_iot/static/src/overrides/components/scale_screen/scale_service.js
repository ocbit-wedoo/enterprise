import { PosScaleService } from "@point_of_sale/app/screens/scale_screen/scale_service";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PosScaleService.prototype, {
    get _scaleDevice() {
        return this.hardwareProxy.deviceControllers.scale;
    },

    get isManualMeasurement() {
        return this._scaleDevice?.manual_measurement;
    },

    reset() {
        if (this.isMeasuring) {
            this._scaleDevice?.removeListener();
            this._scaleDevice?.action({ action: "stop_reading" });
        }
        super.reset(...arguments);
    },

    async _getWeightFromScale() {
        const weightPromise = new Promise((resolve, reject) => {
            this._scaleDevice.addListener((data) => {
                try {
                    resolve(this._handleScaleMessage(data));
                } catch (error) {
                    reject(error);
                }
                this._scaleDevice.removeListener();
            });
        });
        await this._scaleDevice.action({ action: "read_once" });
        return weightPromise;
    },

    _readWeightContinuously() {
        this._scaleDevice.addListener((data) => {
            try {
                this.weight = this._handleScaleMessage(data);
                this._clearLastWeightIfValid();
                this._setTareIfRequested();
            } catch (error) {
                this.onError?.(error.message);
            }
        });
        // The IoT box only sends the weight when it changes, so we
        // manually read to get the initial value.
        this._scaleDevice.action({ action: "read_once" });
        this._scaleDevice.action({ action: "start_reading" });
    },

    _handleScaleMessage(data) {
        if (data.status.status === "error") {
            throw new Error(
                _t("Cannot weigh product – %(msg)s", {
                    msg: data.status.message_body,
                })
            );
        } else if (data.status.status === "connected" || data.status === "success") {
            return data.value || data.result || 0;
        }
        // else, do nothing to avoid data.status === "error"
        // corresponding to timeout because weight did not change
        return this.weight;
    },
});
